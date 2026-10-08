from pathlib import Path
import numpy as np
import pytest
from recognition import common, training, release


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(training, 'ROOT', tmp_path)
    config = {'learning_rate': .0003, 'dropout': .2, 'fine_tune_scope': 'frozen',
              'data_version': 'v1', 'category_version': 'campus-10-v2', 'batch_size': 32,
              'seed': 42, 'augmentation': True, 'max_epochs': 20, 'patience': 3}
    base = tmp_path / 'baseline.json'
    common.write_json(base, config)
    plan = training.sweep(base, 'campaign', 'learning_rate')
    return tmp_path, base, plan


def campaign_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for directory in ('ml/configs/generated', 'experiments')
            for p in (root / directory).rglob('*') if p.is_file()}


@pytest.mark.parametrize('execute', [False, True])
def test_changed_campaign_rejected_before_any_write(campaign, monkeypatch, execute):
    root, base, _ = campaign
    before = campaign_bytes(root)
    config = common.read_json(base)
    config['max_epochs'] = 10
    common.write_json(base, config)
    monkeypatch.setattr(training, 'train', lambda *a, **k: pytest.fail('Conflict must precede training'))
    with pytest.raises(ValueError, match='new campaign'):
        training.sweep(base, 'campaign', 'learning_rate', execute=execute)
    assert campaign_bytes(root) == before


@pytest.mark.parametrize('conflict', ['task', 'result', 'state'])
def test_late_campaign_conflict_preserves_every_file(campaign, monkeypatch, conflict):
    root, base, plan = campaign
    jobs = common.read_json(plan)['jobs']
    last = jobs[-1]
    # Leave the first config absent: preflight must not recreate it before
    # discovering a conflict in the last candidate or its PC task.
    (root / jobs[0]['config']).unlink()
    if conflict == 'task':
        path = plan.parent / 'pc-tasks/learning_rate-pc3.json'
        old = common.read_json(path); old['command'] = ['wrong-command']
        common.write_json(path, old)
    else:
        dataset = root / 'data/splits/v1/dataset.json'
        common.write_json(dataset, {'frozen': True})
        config = common.read_json(root / last['config'])
        identity = {'config': config, 'data_metadata_sha256': common.digest(dataset),
                    'code_snapshot_sha256': 'old-source', 'initial_checkpoint_sha256': None}
        directory = 'reports' if conflict == 'result' else 'checkpoints'
        filename = 'result.json' if conflict == 'result' else 'state.json'
        common.write_json(root / 'experiments' / directory / last['experiment_id'] / filename,
                          {'config': config, 'identity': identity, 'status': 'complete'})
    before = campaign_bytes(root)
    with pytest.raises(ValueError, match='new campaign'):
        training.sweep(base, 'campaign', 'learning_rate')
    assert campaign_bytes(root) == before


def test_identical_campaign_is_byte_preserving_and_can_resume(campaign, monkeypatch):
    root, base, plan = campaign
    jobs = common.read_json(plan)['jobs']
    first = jobs[0]
    config = common.read_json(root / first['config'])
    dataset = root / 'data/splits/v1/dataset.json'
    common.write_json(dataset, {'frozen': True})
    common.write_json(root / 'experiments/checkpoints' / first['experiment_id'] / 'state.json', {
        'identity': {'config': config, 'data_metadata_sha256': common.digest(dataset),
                     'code_snapshot_sha256': training.snapshot(), 'initial_checkpoint_sha256': None}})
    before = campaign_bytes(root)
    calls = []
    def paused(path, name, **kwargs):
        calls.append((name, kwargs['resume']))
        return {'status': 'paused_time_window'}
    monkeypatch.setattr(training, 'train', paused)
    training.sweep(base, 'campaign', 'learning_rate', execute=True)
    assert calls == [(first['experiment_id'], True)]
    assert campaign_bytes(root) == before
    for job in jobs:
        task = common.read_json(plan.parent / 'pc-tasks' / f"learning_rate-pc{job['pc_slot']}.json")
        assert task['config_sha256'] == common.digest(root / job['config'])


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    from PIL import Image
    category_table = common.categories()
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(common, 'ROOT', tmp_path)
    common.write_json(tmp_path / 'shared/categories.json', category_table)
    Image.new('RGB', (128, 128), 'white').save(tmp_path / 'photo.png')
    rows = [{'sample_id': f'{c}-{i}', 'category_id': str(c), 'image_sha256': f'photo-{c}-{i}',
             'image_path': 'photo.png', 'source_dataset': 'field', 'object_id': f'object-{c}-{i}'}
            for c in range(10) for i in range(20)]
    metadata = {'files': {'test': {'sha256': 'manifest-one'}}}
    monkeypatch.setattr(release, 'load_split', lambda version, split, **k:
                        (rows, metadata) if split == 'test' else ([], {}))
    monkeypatch.setattr(release, 'check_isolation', lambda *a: None)
    bundle = tmp_path / 'model'
    bundle.mkdir()
    (bundle / 'model.tflite').write_bytes(b'unchanged-model')
    (bundle / 'labels.txt').write_text('\n'.join(common.EXPECTED_LABELS), encoding='utf-8')
    examples = bundle / 'examples'; examples.mkdir()
    (examples / 'photo.png').write_bytes((tmp_path / 'photo.png').read_bytes())
    release.preprocess(examples / 'photo.png').astype('<f4').tofile(examples / 'input.bin')
    common.write_json(examples / 'manifest.json', [
        {'category_id': c, 'image': 'photo.png', 'tensor': 'input.bin',
         'scores': [1.0] + [0.0] * 9, 'predicted_id': 0} for c in range(10) for _ in range(2)])
    common.write_json(bundle / 'metadata.json', {'status': 'frozen', 'sha256': 'model-one',
                      'labels_sha256': 'labels-one', 'model_version': 'model-v1',
                      'data_version': 'training-v1', 'model_bytes': (bundle / 'model.tflite').stat().st_size,
                      'acceptance': {'independent_field_accuracy': 'pending'}})
    common.write_json(bundle / 'release-files.json', {
        p.relative_to(bundle).as_posix(): common.digest(p) for p in bundle.rglob('*') if p.is_file()})
    calls = []
    class Runner:
        def __init__(self, path):
            self.metadata = common.read_json(path / 'metadata.json')
            self.labels = list(common.EXPECTED_LABELS)
        def predict_tensor(self, array):
            if array.ndim > 1:
                return np.eye(10, dtype=np.float32)[0]
            calls.append(int(array[0]))
            # One error exercises recovery of the error-preview artifact too.
            return np.eye(10, dtype=np.float32)[1 if len(calls) == 1 else int(array[0])]
    monkeypatch.setattr(release, 'LiteRunner', Runner)
    monkeypatch.setattr(release, 'prepare', lambda rows:
                        (np.array([[int(r['category_id'])] for r in rows]),
                         np.array([int(r['category_id']) for r in rows])))
    report = tmp_path / 'experiments/reports/evaluations/model-v1/field-v1-test.json'
    return bundle, report, rows, metadata, calls


@pytest.mark.parametrize('failure', ['plot', 'release_manifest'])
def test_evaluation_resumes_handover_without_replacing_first_scores(evaluation, monkeypatch, failure):
    bundle, report, _, _, calls = evaluation
    import matplotlib.figure
    if failure == 'plot':
        original = matplotlib.figure.Figure.savefig
        monkeypatch.setattr(matplotlib.figure.Figure, 'savefig', lambda *a, **k:
                            (_ for _ in ()).throw(RuntimeError('plot interrupted')))
    else:
        original = release.write_json
        def fail_manifest(path, value):
            if Path(path) == bundle / 'release-files.json':
                raise RuntimeError('manifest interrupted')
            return original(path, value)
        monkeypatch.setattr(release, 'write_json', fail_manifest)
    with pytest.raises(RuntimeError, match='interrupted'):
        release.evaluate(bundle, 'test', 'field-v1', 'model-one')
    evidence = report.read_bytes()
    assert len(calls) == 200
    if failure == 'plot':
        monkeypatch.setattr(matplotlib.figure.Figure, 'savefig', original)
    else:
        monkeypatch.setattr(release, 'write_json', original)
    monkeypatch.setattr(release, 'prepare', lambda *a: pytest.fail('First test predictions must be preserved'))
    resumed = release.evaluate(bundle, 'test', 'field-v1', 'model-one')
    assert report.read_bytes() == evidence
    assert len(calls) == 200
    assert resumed == common.read_json(report)
    assert (bundle / 'evaluation-test.json').read_bytes() == evidence
    assert report.with_name(report.stem + '-errors.png').is_file()
    meta = common.read_json(bundle / 'metadata.json')
    assert meta['acceptance']['independent_field_accuracy']['accuracy_passed']
    for name, expected in common.read_json(bundle / 'release-files.json').items():
        assert common.digest(bundle / name) == expected
    completion = common.read_json(report.with_name(report.stem + '-completion.json'))
    assert completion['report_sha256'] == common.digest(report)
    release.evaluate(bundle, 'test', 'field-v1', 'model-one')
    assert report.read_bytes() == evidence and len(calls) == 200


@pytest.mark.parametrize('filename', ['model.tflite', 'labels.txt', 'examples/input.bin'])
def test_interrupted_annex_still_checks_immutable_release_files(evaluation, monkeypatch, filename):
    bundle, report, _, _, calls = evaluation
    original = release.write_json
    def interrupt(path, value):
        if Path(path) == bundle / 'release-files.json':
            raise RuntimeError('manifest interrupted')
        return original(path, value)
    monkeypatch.setattr(release, 'write_json', interrupt)
    with pytest.raises(RuntimeError):
        release.evaluate(bundle, 'test', 'field-v1', 'model-one')
    evidence = report.read_bytes()
    monkeypatch.setattr(release, 'write_json', original)
    (bundle / filename).write_bytes(b'tampered-file')
    with pytest.raises(ValueError, match='hash mismatch'):
        release.evaluate(bundle, 'test', 'field-v1', 'model-one')
    assert report.read_bytes() == evidence and len(calls) == 200


@pytest.mark.parametrize('changed', ['model', 'manifest', 'labels', 'sample', 'threshold'])
def test_pending_evaluation_refuses_changed_identity(evaluation, monkeypatch, changed):
    bundle, report, rows, metadata, calls = evaluation
    import matplotlib.figure
    monkeypatch.setattr(matplotlib.figure.Figure, 'savefig', lambda *a, **k:
                        (_ for _ in ()).throw(RuntimeError('plot interrupted')))
    with pytest.raises(RuntimeError):
        release.evaluate(bundle, 'test', 'field-v1', 'model-one')
    evidence = report.read_bytes()
    meta = common.read_json(bundle / 'metadata.json')
    if changed == 'model': meta['sha256'] = 'different-model'
    if changed == 'labels': meta['labels_sha256'] = 'different-labels'
    if changed == 'threshold': meta['low_confidence_threshold'] = .75
    common.write_json(bundle / 'metadata.json', meta)
    if changed == 'manifest': metadata['files']['test']['sha256'] = 'different-manifest'
    if changed == 'sample': rows[0]['sample_id'] = 'different-sample'
    monkeypatch.setattr(release, 'prepare', lambda *a: pytest.fail('Changed identity must precede inference'))
    with pytest.raises(ValueError, match='identity|different model'):
        release.evaluate(bundle, 'test', 'field-v1', meta['sha256'])
    assert report.read_bytes() == evidence and len(calls) == 200
