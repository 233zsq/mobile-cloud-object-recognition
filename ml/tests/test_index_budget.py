import io
import pytest
from recognition import collect, common


LABELS = b'ImageID,LabelName,Confidence\na,/m/0bt_c3,1\n'
IMAGES = 'ImageID,OriginalLandingURL,OriginalURL,Author,License\nb,,,,作者\n'.encode('utf-8')


class Response(io.BytesIO):
    def __init__(self, blob, interrupted=False):
        super().__init__(blob)
        self.headers = {} if interrupted else {'Content-Length': str(len(blob))}
        self.interrupted = interrupted
        self.received = 0

    def read(self, size=-1):
        if self.interrupted and self.tell() == len(self.getvalue()):
            raise OSError('connection interrupted')
        chunk = super().read(size)
        self.received += len(chunk)
        return chunk


@pytest.fixture
def index_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, 'ROOT', tmp_path)
    monkeypatch.setattr(collect, 'INDEX_CHUNK_BYTES', 16, raising=False)
    return tmp_path / 'data/raw/openimages-index'


def test_train_disconnects_share_durable_budget_and_limit_each_read(index_workspace, monkeypatch):
    monkeypatch.setattr(collect, 'INDEX_BUDGET', 70, raising=False)
    responses = []
    def urlopen(*a, **k):
        response = Response(LABELS, interrupted=True)
        responses.append(response)
        return response
    monkeypatch.setattr(collect.urllib.request, 'urlopen', urlopen)
    with pytest.raises(OSError, match='interrupted'):
        collect.collect_openimages(['book'], 1, 'train')
    ledger = common.read_json(index_workspace / 'budget.json')
    assert ledger['bytes'] >= len(LABELS)
    assert ledger['train_scan_bytes'] == ledger['bytes']
    assert not (index_workspace / 'scan.json').exists()
    with pytest.raises(ValueError, match='budget exceeded'):
        collect.collect_openimages(['book'], 1, 'train')
    assert common.read_json(index_workspace / 'budget.json')['bytes'] == 70
    assert sum(r.received for r in responses) <= 70
    opened = len(responses)
    with pytest.raises(ValueError, match='budget exceeded'):
        collect.collect_openimages(['book'], 1, 'train')
    with pytest.raises(ValueError, match='budget exceeded'):
        collect.collect_openimages(['book'], 1, 'validation')
    assert len(responses) == opened


def test_train_scan_inherits_existing_small_index_budget(index_workspace, monkeypatch):
    monkeypatch.setattr(collect, 'INDEX_BUDGET', 100, raising=False)
    common.write_json(index_workspace / 'budget.json', {'bytes': 90, 'files': {'old.csv': {'sha256': 'old'}}})
    response = Response(LABELS, interrupted=True)
    monkeypatch.setattr(collect.urllib.request, 'urlopen', lambda *a, **k: response)
    with pytest.raises(ValueError, match='budget exceeded'):
        collect.collect_openimages(['book'], 1, 'train')
    ledger = common.read_json(index_workspace / 'budget.json')
    assert ledger['bytes'] == 100 and ledger['train_scan_bytes'] == 10
    assert ledger['files']['old.csv']['sha256'] == 'old'
    assert response.received == 10


def test_train_and_cached_small_indexes_count_each_transfer_once(index_workspace, monkeypatch):
    train_bytes = len(LABELS) + 3 + len(IMAGES)
    monkeypatch.setattr(collect, 'INDEX_BUDGET', 2 * train_bytes, raising=False)
    requests = []
    def urlopen(request, **k):
        requests.append(request.full_url)
        return Response(b'\xef\xbb\xbf' + LABELS if 'imagelabels' in request.full_url else IMAGES)
    monkeypatch.setattr(collect.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(collect, 'fetch', lambda *a, **k: pytest.fail('No selected metadata photo'))
    assert collect.collect_openimages(['book'], 1, 'train') == []
    assert common.read_json(index_workspace / 'scan.json')['selected'] == {'a': 'book'}
    assert collect.collect_openimages(['book'], 1, 'validation') == []
    ledger = common.read_json(index_workspace / 'budget.json')
    assert ledger['bytes'] == 2 * train_bytes
    assert ledger['train_scan_bytes'] == train_bytes
    assert collect.collect_openimages(['book'], 1, 'validation') == []
    assert len(requests) == 4
    assert common.read_json(index_workspace / 'budget.json')['bytes'] == ledger['bytes']


def test_legacy_scan_is_added_once_to_existing_small_ledger(index_workspace, monkeypatch):
    monkeypatch.setattr(collect, 'INDEX_BUDGET', 1000, raising=False)
    common.write_json(index_workspace / 'scan.json', {'bytes': 100})
    common.write_json(index_workspace / 'budget.json', {'bytes': 20, 'files': {}})
    monkeypatch.setattr(collect.urllib.request, 'urlopen', lambda request, **k:
                        Response(LABELS if 'imagelabels' in request.full_url else IMAGES))
    collect.collect_openimages(['book'], 1, 'validation')
    expected = 120 + len(LABELS) + len(IMAGES)
    assert common.read_json(index_workspace / 'budget.json')['bytes'] == expected
    collect.collect_openimages(['book'], 1, 'validation')
    assert common.read_json(index_workspace / 'budget.json')['bytes'] == expected


@pytest.mark.parametrize('provider', ['train', 'validation'])
def test_known_index_size_over_remaining_budget_is_refused_before_body(index_workspace, monkeypatch, provider):
    monkeypatch.setattr(collect, 'INDEX_BUDGET', 100, raising=False)
    common.write_json(index_workspace / 'budget.json', {'bytes': 90, 'files': {}})
    response = Response(LABELS)
    def forbidden_read(size):
        pytest.fail('Oversize index body must not be read')
    response.read = forbidden_read
    monkeypatch.setattr(collect.urllib.request, 'urlopen', lambda *a, **k: response)
    with pytest.raises(ValueError, match='budget exceeded'):
        collect.collect_openimages(['book'], 1, provider)
    assert common.read_json(index_workspace / 'budget.json')['bytes'] == 90


def test_read_reservation_survives_process_interruption(index_workspace, monkeypatch):
    monkeypatch.setattr(collect, 'INDEX_BUDGET', 16, raising=False)
    opened = []
    def urlopen(*a, **k):
        opened.append(True)
        response = Response(LABELS, interrupted=True)
        def interrupted_read(size):
            ledger = common.read_json(index_workspace / 'budget.json')
            assert ledger['bytes'] == size == 16 and ledger['uncertain_bytes'] == 16
            raise KeyboardInterrupt()
        response.read = interrupted_read
        return response
    monkeypatch.setattr(collect.urllib.request, 'urlopen', urlopen)
    with pytest.raises(KeyboardInterrupt):
        collect.collect_openimages(['book'], 1, 'train')
    assert common.read_json(index_workspace / 'budget.json')['bytes'] == 16
    with pytest.raises(ValueError, match='budget exceeded'):
        collect.collect_openimages(['book'], 1, 'validation')
    assert len(opened) == 1
