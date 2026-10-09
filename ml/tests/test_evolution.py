import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from recognition import common, data, evolution, training, release


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    source = common.ROOT
    for module in (common, data, evolution, training, release):
        monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'shared').mkdir()
    (tmp_path / 'shared/categories.json').write_bytes((source / 'shared/categories.json').read_bytes())
    policy = tmp_path / 'shared/category-versions/campus-10-v3.json'
    policy.parent.mkdir()
    policy.write_bytes((source / 'shared/category-versions/campus-10-v3.json').read_bytes())
    common.write_json(tmp_path / 'ml/configs/baseline.json', common.read_json(source / 'ml/configs/baseline.json'))
    parent = tmp_path / 'experiments/checkpoints/parent/best.keras'
    parent.parent.mkdir(parents=True); parent.write_bytes(b'test-only-parent')
    common.write_json(tmp_path / 'models/releases/campus-gpu-v1/metadata.json', {
        'status': 'frozen', 'category_version': 'campus-10-v2', 'experiment_id': 'parent', 'data_version':'base',
        'checkpoint_sha256': common.digest(parent), 'sha256': 'a' * 64})
    rng = np.random.default_rng(3)
    def row(sid, category=0):
        path = tmp_path / 'data/raw' / (sid + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rng.integers(0, 256, (128, 128, 3), np.uint8)).save(path)
        with Image.open(path) as im:
            fingerprint = data.phash(im)
        return {'sample_id': sid, 'image_path': path.relative_to(tmp_path).as_posix(),
                'image_sha256': common.digest(path), 'category_id': str(category), 'object_id': sid,
                'session_id': 'test-session', 'group_id': sid, 'phash': fingerprint,
                'review_status': 'approved', 'source_dataset': 'field'}
    metadata = {'status': 'frozen', 'data_version': 'base', 'category_version': 'campus-10-v2',
                'categories_sha256': common.digest(tmp_path / 'shared/categories.json'), 'files': {}}
    for name in ('train', 'validation'):
        rows = [row(name + str(i), i) for i in range(10)]
        for r in rows:
            r.update(split_name=name, data_version='base', source_dataset='public-test-fixture')
        path = tmp_path / 'data/splits/base' / (name + '.csv')
        common.write_csv(path, rows)
        metadata['files'][name] = {'sha256': common.digest(path), 'count': 10}
    common.write_json(tmp_path / 'data/splits/base/dataset.json', metadata)
    def archive(rows, name='batch.zip', category_version='campus-10-v2'):
        records = [{**r, 'image_path': 'images/' + Path(r['image_path']).name} for r in rows]
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
        payload = stream.getvalue().encode()
        receipt = {'purpose': 'training_only', 'category_version': category_version,
                   'categories_sha256': common.digest(common.category_path(category_version)), 'batch_id': 'test-batch',
                   'count': len(rows), 'files': {'samples.csv': hashlib.sha256(payload).hexdigest(),
                    **{r['image_path']: r['image_sha256'] for r in records}}}
        path = tmp_path / name
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('batch.json', json.dumps(receipt)); z.writestr('samples.csv', payload)
            for a, b in zip(rows, records):
                z.write(tmp_path / a['image_path'], b['image_path'])
        return path
    return tmp_path, row, archive


def test_keyboard_scope_migration_keeps_baseline_and_records_new_categories(workspace):
    root, row, archive = workspace
    baseline = root / 'data/splits/base/dataset.json'
    parent = root / 'models/releases/campus-gpu-v1/metadata.json'
    before = {p: common.digest(p) for p in (baseline, parent, root / 'shared/categories.json')}
    package = archive([row('laptop-keyboard', 5)], category_version='campus-10-v3')
    result = evolution.import_batch(package, 'v3-first', 'base')
    config = common.read_json(root / 'ml/configs/generated/v3-first.json')
    assert result['category_version'] == config['category_version'] == 'campus-10-v3'
    assert result['category_transition']['change'] == 'keyboard_includes_laptop_built_in'
    _, lineage = evolution.resolve_parent(config)
    assert lineage['category_transition'] == result['category_transition']
    assert len(data.load_split('v3-first', 'train')[0]) == 11
    assert all(common.digest(p) == expected for p, expected in before.items())
    next_package = archive([row('another-keyboard', 5)], 'second-v3.zip', 'campus-10-v3')
    assert evolution.import_batch(next_package, 'v3-second', 'v3-first')['category_version'] == 'campus-10-v3'
    with pytest.raises(ValueError, match='Unsupported category transition'):
        evolution.import_batch(archive([row('old-policy', 5)]), 'narrowed', 'v3-second')
    assert not (root / 'data/splits/narrowed').exists()


def test_keyboard_transition_does_not_permit_other_category_changes(workspace):
    root, row, archive = workspace
    policy = common.category_path('campus-10-v3')
    changed = common.read_json(policy)
    changed['categories'][2]['definition'] = 'changed book scope'
    common.write_json(policy, changed)
    with pytest.raises(ValueError, match='unrelated definitions'):
        evolution.import_batch(archive([row('unrelated')], category_version='campus-10-v3'), 'bad-policy', 'base')
    assert not (root / 'data/splits/bad-policy').exists()


def test_import_preserves_every_old_assignment_and_parent(workspace):
    root, row, archive = workspace
    before = {name: common.read_csv(root / 'data/splits/base' / (name + '.csv')) for name in ('train', 'validation')}
    new = [row('field-' + str(i)) for i in range(4)]
    result = evolution.import_batch(archive(new), 'evolve-1', 'base')
    assert result['new_train_count'] == 3 and result['new_validation_count'] == 1
    for name, old in before.items():
        current, _ = data.load_split('evolve-1', name)
        for a, b in zip(old, current):
            assert {k: v for k, v in a.items() if k != 'data_version'} == {k: b[k] for k in a if k != 'data_version'}
            assert not any(b.get(k) for k in evolution.EVOLUTION_FIELDS if k not in common.FIELDS)
    config = common.read_json(root / 'ml/configs/generated/evolve-1.json')
    checkpoint, lineage = evolution.resolve_parent(config)
    assert lineage['checkpoint_sha256'] == common.digest(checkpoint)
    checkpoint.write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash changed'):
        evolution.resolve_parent(config)


def test_new_photo_related_to_old_validation_stays_in_validation(workspace):
    root, row, archive = workspace
    new = row('field-validation')
    new['object_id'] = 'validation0'
    result = evolution.import_batch(archive([new]), 'related', 'base')
    assert result['new_train_count'] == 0 and result['new_validation_count'] == 1


def public_row(row):
    return {**row, 'source_dataset': 'wikimedia_commons', 'source_id': 'test-source',
            'source_sample_id': 'commons-test-source', 'object_id': '',
            'source_url': 'https://commons.wikimedia.org/wiki/File:Test.jpg',
            'original_url': 'https://upload.wikimedia.org/test.jpg', 'license': 'CC BY 4.0'}


def test_public_crop_keeps_original_lineage_and_actual_pixels(workspace):
    root, row, archive = workspace
    new = public_row(row('public-crop'))
    original = root/new['image_path']
    Image.fromarray(np.random.default_rng(947).integers(0, 256, (256, 256, 3), np.uint8)).save(original)
    new['image_sha256'] = common.digest(original)
    new['crop_box'] = '[32,32,224,224]'
    result = evolution.import_batch(archive([new]), 'public-crop', 'base')
    assert result['new_train_count'] == 1
    selected = common.read_csv(root/'data/splits/public-crop/train.csv')[-1]
    assert selected['image_sha256'] != selected['parent_image_sha256'] == common.digest(original)
    assert '/derived/' in selected['image_path'] and selected['license'] == 'CC BY 4.0'
    with Image.open(root/selected['image_path']) as im:
        assert im.size == (192, 192)
    assert (root/'data/raw/evolution/public-crop/images'/original.name).read_bytes() == original.read_bytes()
    with pytest.raises(ValueError, match='leakage'):
        data.check_isolation([new], [selected])


def test_cropped_old_validation_photo_cannot_enter_training(workspace):
    root, row, archive = workspace
    old = common.read_csv(root/'data/splits/base/validation.csv')[0]
    new = public_row(row('validation-crop'))
    (root/new['image_path']).write_bytes((root/old['image_path']).read_bytes())
    new.update(image_sha256=old['image_sha256'], crop_box='[0,0,128,128]', source_sample_id=old['sample_id'])
    result = evolution.import_batch(archive([new]), 'validation-crop', 'base')
    assert result['new_train_count'] == 0 and result['new_validation_count'] == 1


def test_crop_of_frozen_test_photo_is_rejected_by_parent_identity(workspace):
    root, row, archive = workspace
    heldout = row('heldout')
    manifest = root/'data/splits/field-v1/test.csv'
    common.write_csv(manifest, [heldout])
    common.write_json(manifest.parent/'dataset.json', {'status':'frozen', 'files':{'test':{'sha256':common.digest(manifest)}}})
    new = public_row(heldout); new.update(sample_id='new-crop', crop_box='[0,0,128,128]')
    with pytest.raises(ValueError, match='Independent test identity'):
        evolution.import_batch(archive([new]), 'test-crop', 'base')


@pytest.mark.parametrize('box', ['[-1,0,128,128]', '[0,0,129,128]', '[0,0,64,128]', '[0.0,0,128,128]'])
def test_invalid_crop_box_is_rejected(workspace, box):
    root, row, archive = workspace
    new = row('bad-crop'); new['crop_box'] = box
    with pytest.raises(ValueError, match='Invalid crop'):
        evolution.import_batch(archive([new]), 'bad-crop', 'base')


def test_bridge_of_existing_train_and_validation_is_rejected(workspace):
    root, row, archive = workspace
    new=row('bridge');new['object_id']='train0';new['group_id']='validation0'
    with pytest.raises(ValueError,match='bridges old train/validation'):
        evolution.import_batch(archive([new]),'bridge','base')
    assert not (root/'data/raw/evolution/bridge').exists()
    assert not (root/'data/splits/bridge').exists()


def test_later_batch_keeps_all_previously_reviewed_photos(workspace):
    root,row,archive=workspace
    first=[row('first-1'),row('first-2')]
    evolution.import_batch(archive(first,'first.zip'),'first','base')
    second=[row('second-1',1),row('second-2',1)]
    result=evolution.import_batch(archive(second,'second.zip'),'second','first')
    current=[r for name in ('train','validation') for r in data.load_split('second',name)[0]]
    assert result['files']['train']['count']+result['files']['validation']['count']==24
    assert {r['sample_id'] for r in first+second}<={r['sample_id'] for r in current}


def test_parent_configuration_cannot_enter_imagenet_sweep(tmp_path):
    path=tmp_path/'parent.json';common.write_json(path,{'training_mode':'parent_finetune'})
    with pytest.raises(ValueError,match='explicit train configurations'):
        training.sweep(path,'new','learning_rate')


def test_approval_receipt_binds_report_and_model(workspace,monkeypatch):
    root,_,_=workspace
    monkeypatch.setattr(release,'verify',lambda path: {'passed':True})
    directory=root/'models/releases/candidate'
    common.write_json(directory/'metadata.json',{'model_version':'candidate','sha256':'b'*64})
    report=root/'comparison.json';common.write_json(report,{'candidate':{'sha256':'b'*64}})
    receipt=root/'approval.json'
    approved={'status':'approved','model_version':'candidate','model_sha256':'b'*64,
              'report_sha256':common.digest(report),'approved_by':'admin','approved_at':'2026-10-09','reason':'verified'}
    common.write_json(receipt,{**approved,'model_sha256':'wrong'})
    with pytest.raises(ValueError,match='identities differ'):
        evolution.accept_approval(directory,receipt,report)
    common.write_json(receipt,approved)
    evolution.accept_approval(directory,receipt,report)
    assert common.read_json(directory/'approval.json')==approved


def test_test_identity_and_unsafe_archive_are_rejected(workspace):
    root, row, archive = workspace
    test = row('held-out')
    test.update(split_name='test', data_version='test-v1')
    path = root / 'data/splits/test-v1/test.csv'; common.write_csv(path, [test])
    common.write_json(path.parent / 'dataset.json', {'status': 'frozen', 'files': {'test': {'sha256': common.digest(path)}}})
    with pytest.raises(ValueError, match='Independent test identity'):
        evolution.import_batch(archive([test]), 'forbidden', 'base')
    assert not (root / 'data/splits/forbidden').exists()
    bad = root / 'unsafe.zip'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('../outside.txt', 'bad')
    with pytest.raises(ValueError, match='Unsafe ZIP'):
        evolution.import_batch(bad, 'unsafe', 'base')


@pytest.mark.parametrize('seed', [43, 44])
def test_parent_reproduction_does_not_rebuild_an_imagenet_head(tmp_path, monkeypatch, seed):
    monkeypatch.setattr(training, 'ROOT', tmp_path)
    primary = {'status': 'complete', 'experiment_id': 'primary', 'config': {
        'training_mode': 'parent_finetune', 'parent_checkpoint': 'fixed/best.keras',
        'fine_tune_scope': 'last_1', 'learning_rate': .0001, 'seed': 42},
        'identity': {'initial_checkpoint_sha256': 'fixed'}, 'validation': {'macro_f1': .8}}
    path = tmp_path / 'result.json'; common.write_json(path, primary)
    calls = []
    def fake_train(config_path, name, **kwargs):
        calls.append((common.read_json(config_path), kwargs))
        return {'status': 'complete', 'validation': {'macro_f1': .81}}
    monkeypatch.setattr(training, 'train', fake_train)
    training.reproduce(path, seed)
    assert len(calls) == 1 and calls[0][0]['seed'] == seed
    assert calls[0][1]['initial_checkpoint'] == tmp_path / 'fixed/best.keras'


def test_export_rejects_a_different_parent_even_if_config_matches(monkeypatch):
    expected = {'checkpoint_sha256': 'same', 'model_version': 'baseline'}
    monkeypatch.setattr(evolution, 'resolve_parent', lambda c: (None, expected))
    primary = {'config': {'training_mode': 'parent_finetune'},
               'identity': {'parent_lineage': expected, 'initial_checkpoint_sha256': 'same'}}
    wrong = {**primary, 'identity': {**primary['identity'], 'initial_checkpoint_sha256': 'different'}}
    with pytest.raises(ValueError, match='parent lineage'):
        release.validate_parent_reproduction(primary, wrong)


@pytest.mark.integration
@pytest.mark.parametrize('category_version', ['campus-10-v2', 'campus-10-v3'])
def test_real_parent_gradient_and_repeat_use_fresh_optimizer_and_rng(workspace, monkeypatch, category_version):
    """A tiny synthetic network tests orchestration, never object accuracy."""
    import keras
    import tensorflow as tf
    for gpu in tf.config.list_physical_devices('GPU'):
        tf.config.experimental.set_memory_growth(gpu,True)
    root, row, archive = workspace
    inputs = keras.Input((224, 224, 3))
    inner_input = keras.Input((224, 224, 3))
    inner = keras.layers.Conv2D(4, 1, name='Conv_1')(inner_input)
    inner = keras.layers.BatchNormalization()(inner)
    backbone = keras.Model(inner_input, inner, name='test_backbone')
    x = keras.layers.Rescaling(1/127.5, offset=-1)(inputs)
    x = backbone(x, training=False)
    x = keras.layers.GlobalAveragePooling2D()(x)
    x = keras.layers.Dropout(.4, seed=42)(x)
    model = keras.Model(inputs, keras.layers.Dense(10, activation='softmax', name='class_scores')(x))
    model.compile(optimizer=keras.optimizers.Adam(.001), loss='sparse_categorical_crossentropy')
    model.optimizer.iterations.assign(17)
    checkpoint = root/'experiments/checkpoints/parent/best.keras'
    model.save(checkpoint)
    parent_path = root/'models/releases/campus-gpu-v1/metadata.json'
    metadata = common.read_json(parent_path); metadata['checkpoint_sha256']=common.digest(checkpoint)
    common.write_json(parent_path, metadata)
    evolution.import_batch(archive([row('new-1'),row('new-2')], category_version=category_version),'real-parent','base')
    path=root/'ml/configs/generated/real-parent.json'
    config=common.read_json(path);config['max_epochs']=1;common.write_json(path,config)
    from datetime import datetime as real_datetime
    class Noon(real_datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,10,9,12,tzinfo=common.TZ)
    monkeypatch.setattr(training,'datetime',Noon)
    primary=training.train(path,'parent42')
    repeat=training.reproduce(root/'experiments/reports/parent42/result.json')
    assert primary['identity']['parent_lineage']==repeat['identity']['parent_lineage']
    restored=keras.models.load_model(root/repeat['checkpoint'])
    assert int(restored.optimizer.iterations)==1
    assert training.dropout_rng_state(restored)[next(l.name for l in restored.layers if isinstance(l,keras.layers.Dropout))][0]==43
    bn=next(l for l in next(l for l in restored.layers if isinstance(l,keras.Model)).layers if isinstance(l,keras.layers.BatchNormalization))
    assert not bn.trainable
    np.testing.assert_array_equal(bn.moving_mean.numpy(),np.zeros(4))
    assert common.digest(checkpoint)==metadata['checkpoint_sha256']
