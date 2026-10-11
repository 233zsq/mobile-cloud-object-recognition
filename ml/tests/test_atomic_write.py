from pathlib import Path

import pytest

from recognition import common


@pytest.mark.parametrize('kind', ['csv', 'json'])
def test_atomic_write_retries_windows_handle_conflict(tmp_path, monkeypatch, kind):
    destination = tmp_path / ('manifest.' + kind)
    destination.write_text('previous', encoding='utf-8')
    replace = Path.replace
    attempts = []
    waits = []

    def briefly_locked(temporary, target):
        attempts.append(temporary)
        if len(attempts) <= 2:
            assert destination.read_text(encoding='utf-8') == 'previous'
            error = PermissionError('Windows reader still holds the old file')
            error.winerror = 32
            raise error
        return replace(temporary, target)

    monkeypatch.setattr(Path, 'replace', briefly_locked)
    monkeypatch.setattr(common.time, 'sleep', waits.append)
    if kind == 'csv':
        common.write_csv(destination, [{'sample_id': 'sample-1'}])
        assert common.read_csv(destination)[0]['sample_id'] == 'sample-1'
    else:
        common.write_json(destination, {'downloaded': 438})
        assert common.read_json(destination) == {'downloaded': 438}
    assert len(attempts) == 3 and waits == [0.05, 0.1]


@pytest.mark.parametrize('winerror,expected_attempts', [(5, 7), (None, 1)])
def test_persistent_permission_error_preserves_previous_file(tmp_path, monkeypatch, winerror, expected_attempts):
    destination = tmp_path / 'manifest.csv'
    destination.write_text('previous', encoding='utf-8')
    attempts = []

    def denied(temporary, target):
        attempts.append(temporary)
        error = PermissionError('denied')
        if winerror is not None:
            error.winerror = winerror
        raise error

    monkeypatch.setattr(Path, 'replace', denied)
    monkeypatch.setattr(common.time, 'sleep', lambda _: None)
    with pytest.raises(PermissionError):
        common.write_csv(destination, [{'sample_id': 'new'}])
    assert len(attempts) == expected_attempts
    assert destination.read_text(encoding='utf-8') == 'previous'
