"""Reviewed field batches, stable development splits and immutable parent lineage."""
import csv
import io
import json
import random
import shutil
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps

from .common import ROOT, FIELDS, categories, category_path, digest, image_path, now, read_csv, read_json, safe_name, write_csv, write_json
from .data import check_isolation, connected_groups, load_split, phash, identity_keys, perceptual_keys

EVOLUTION_FIELDS = FIELDS + ['source_sample_id', 'crop_box', 'parent_image_sha256', 'parent_phash']


def resolve_parent(config, initial_checkpoint=None):
    if config.get('training_mode') != 'parent_finetune':
        return initial_checkpoint, None
    version = safe_name(config['parent_release'])
    metadata_path = ROOT / 'models/releases' / version / 'metadata.json'
    metadata = read_json(metadata_path)
    checkpoint = image_path(config['parent_checkpoint'])
    if metadata['status'] != 'frozen' or metadata['category_version'] != config['category_version']:
        raise ValueError('Parent release must be frozen with the same categories')
    if metadata.get('deployment_approval') == 'pending_human_approval':
        approval = read_json(metadata_path.parent / 'approval.json')
        if approval.get('status')!='approved' or approval.get('model_sha256')!=metadata['sha256']:
            raise ValueError('Evolution parent must have matching human approval')
    if digest(metadata_path) != config['parent_metadata_sha256'] or digest(checkpoint) != metadata['checkpoint_sha256']:
        raise ValueError('Parent metadata/checkpoint hash changed')
    if initial_checkpoint and Path(initial_checkpoint).resolve() != checkpoint:
        raise ValueError('Initial checkpoint differs from immutable parent')
    lineage = {'model_version': version, 'model_sha256': metadata['sha256'],
               'metadata_sha256': digest(metadata_path), 'checkpoint': checkpoint.relative_to(ROOT).as_posix(),
               'checkpoint_sha256': digest(checkpoint)}
    return checkpoint, lineage


def identities(row):
    return identity_keys(row)


def overlaps(a, b):
    return bool(identities(a) & identities(b)) or any((x ^ y).bit_count() <= 6 for x in perceptual_keys(a) for y in perceptual_keys(b))


def import_batch(archive, version, base_version='campus-public-expanded-v1', parent_release='campus-gpu-v1'):
    """Keep every old assignment; only split new, independent approved groups."""
    safe_name(version); safe_name(parent_release)
    archive_identity=digest(archive)
    destination = ROOT / 'data/raw/evolution' / version
    split_dir = ROOT / 'data/splits' / version
    if destination.exists() or split_dir.exists():
        raise ValueError('Evolution version exists; choose a new immutable version')
    train, base = load_split(base_version, 'train')
    val, _ = load_split(base_version, 'validation')
    parent = read_json(ROOT / 'models/releases' / parent_release / 'metadata.json')
    cursor=base_version
    visited=set()
    while cursor!=parent['data_version']:
        if cursor in visited:
            raise ValueError('Dataset ancestry contains a cycle')
        visited.add(cursor)
        ancestor=read_json(ROOT/'data/splits'/safe_name(cursor)/'dataset.json')
        previous=ancestor.get('base_data_version')
        if not previous or digest(ROOT/'data/splits'/safe_name(previous)/'dataset.json')!=ancestor.get('base_metadata_sha256'):
            raise ValueError('Base data must retain the parent training dataset')
        cursor=previous
    config = read_json(ROOT / 'ml/configs/baseline.json')
    config.update(training_mode='parent_finetune', parent_release=parent_release,
                  parent_metadata_sha256=digest(ROOT / 'models/releases' / parent_release / 'metadata.json'),
                  parent_checkpoint=f"experiments/checkpoints/{parent['experiment_id']}/best.keras",
                  data_version=version, dropout=.4, learning_rate=.0001, fine_tune_scope='last_1')
    resolve_parent(config)
    check_isolation(train, val)
    heldout = []
    # Read only frozen test manifest identities, never the test images.
    for manifest in (ROOT / 'data/splits').glob('*/test.csv'):
        metadata = read_json(manifest.parent / 'dataset.json')
        if metadata.get('status') != 'frozen' or digest(manifest) != metadata['files']['test']['sha256']:
            raise ValueError('Held-out test manifest changed')
        heldout.extend(read_csv(manifest))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='import-', dir=destination.parent) as temp:
        staging = Path(temp)
        with zipfile.ZipFile(archive) as package:
            infos = package.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > 10002 or sum(i.file_size for i in infos) > 3 * 1024**3:
                raise ValueError('Duplicate ZIP paths or batch budget exceeded')
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or info.file_size > 8 * 1024**2:
                    raise ValueError('Unsafe ZIP path or file size')
            receipt = json.loads(package.read('batch.json'))
            if receipt.get('purpose') != 'training_only' or receipt['category_version'] != base['category_version'] or receipt['categories_sha256'] != digest(category_path(base['category_version'])):
                raise ValueError('Batch purpose/category identity differs')
            if set(names) != {'batch.json', *receipt['files']}:
                raise ValueError('Unlisted/missing ZIP files')
            for name, expected in receipt['files'].items():
                content = package.read(name)
                import hashlib
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError('Batch file hash mismatch')
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        rows = list(csv.DictReader(io.StringIO((staging / 'samples.csv').read_text(encoding='utf-8'))))
        if not rows or len(rows) != receipt['count'] or len({r['sample_id'] for r in rows}) != len(rows):
            raise ValueError('Batch sample count/identity differs')
        if len({r['image_sha256'] for r in rows}) != len(rows):
            raise ValueError('Duplicate batch photo')
        expected_images = {r['image_path'] for r in rows}
        if set(receipt['files']) != {'samples.csv', *expected_images}:
            raise ValueError('Manifest and image paths differ')
        for row in rows:
            path = PurePosixPath(row['image_path'])
            source = row.get('source_dataset')
            public = source in ('wikimedia_commons', 'open_images')
            if len(path.parts) != 2 or path.parts[0] != 'images' or source not in ('field', 'wikimedia_commons', 'open_images') or row['review_status'] != 'approved' or (not public and not row['object_id']) or not row['session_id'] or not row['group_id'] or int(row['category_id']) not in range(10):
                raise ValueError('Approved photo identity/label missing')
            if public and not all(row.get(k) for k in ('source_id', 'source_url', 'original_url', 'license', 'source_sample_id')):
                raise ValueError('Public source attribution missing')
            photo = staging / path
            if digest(photo) != row['image_sha256']:
                raise ValueError('Manifest photo hash mismatch')
            with Image.open(photo) as im:
                if im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'n_frames', 1) != 1 or im.width * im.height > 16_000_000:
                    raise ValueError('Batch image format/frame/pixel budget exceeded')
                im.load()
                corrected = ImageOps.exif_transpose(im).convert('RGB')
                if min(corrected.size) < 128:
                    raise ValueError('Field photo too small')
                row['phash'] = phash(im)
                # Always compute parent identity locally, never trust supplied lineage hashes.
                row['parent_image_sha256'] = row['image_sha256']
                row['parent_phash'] = row['phash']
                if row.get('crop_box'):
                    box = json.loads(row['crop_box'])
                    if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= corrected.width and 0 <= box[1] < box[3] <= corrected.height) or min(box[2]-box[0], box[3]-box[1]) < 128:
                        raise ValueError('Invalid crop box')
                    photo = staging / 'derived' / (safe_name(row['sample_id']) + '.jpg')
                    photo.parent.mkdir(exist_ok=True)
                    cropped = corrected.crop(box)
                    cropped.save(photo, 'JPEG', quality=95, subsampling=0)
                    if photo.stat().st_size > 8 * 1024**2:
                        raise ValueError('Derived crop exceeds image budget')
                    row['image_sha256'] = digest(photo)
                    row['phash'] = phash(cropped)
                    row['width'], row['height'] = map(str, cropped.size)
            if any(overlaps(row, t) for t in heldout):
                raise ValueError('Independent test identity cannot enter development data')
            if any(row['image_sha256'] == r['image_sha256'] or row['sample_id'] == r['sample_id'] for r in train + val):
                raise ValueError('Photo already present in base dataset')
            row['image_path'] = (destination / photo.relative_to(staging)).relative_to(ROOT).as_posix()
        # Union perceptual neighbours as well as the human-reviewed identity graph.
        for i, row in enumerate(rows):
            related = [r for r in rows[:i] if overlaps(row, r)]
            if related:
                merged = {r['group_id'] for r in related} | {row['group_id']}
                group = min(merged)
                for r in rows:
                    if r['group_id'] in merged:
                        r['group_id'] = group
        groups = connected_groups(rows)
        if any(len({r['category_id'] for r in group}) != 1 for group in groups):
            raise ValueError('Connected group has conflicting labels; re-review batch')
        added_train, added_val, independent = [], [], []
        for group in groups:
            linked_train = any(overlaps(a, b) for a in group for b in train)
            linked_val = any(overlaps(a, b) for a in group for b in val)
            if linked_train and linked_val:
                raise ValueError('New group bridges old train/validation identities')
            if any(overlaps(a, b) and a['category_id'] != b['category_id'] for a in group for b in train + val):
                raise ValueError('New photo conflicts with a related base category')
            (added_train if linked_train else added_val if linked_val else independent).append(group)
        rng = random.Random(42)
        for category in range(10):
            subset = [g for g in independent if int(g[0]['category_id']) == category]
            rng.shuffle(subset)
            if len(subset) < 2:
                added_train.extend(subset)
                continue
            target = sum(map(len, subset)) * .25
            selected = 0
            for index, group in enumerate(subset):
                use_val = index < len(subset) - 1 and (selected == 0 or abs(selected + len(group) - target) < abs(selected - target))
                (added_val if use_val else added_train).append(group)
                if use_val:
                    selected += len(group)
        new_train = [r for group in added_train for r in group]
        new_val = [r for group in added_val for r in group]
        all_train, all_val = train + new_train, val + new_val
        check_isolation(all_train, all_val, heldout)
        if digest(archive)!=archive_identity:
            raise ValueError('Batch archive changed during import')
        # Validate everything before publishing either directory.
        shutil.copytree(staging, destination)
    metadata = {'status': 'frozen', 'purpose': 'evolution_development', 'data_version': version,
                'category_version': base['category_version'], 'categories_sha256': base['categories_sha256'],
                'created_at': now(), 'seed': 42, 'base_data_version': base_version,
                'base_metadata_sha256': digest(ROOT / 'data/splits' / base_version / 'dataset.json'),
                'source_archive_sha256': archive_identity, 'batch_id': receipt['batch_id'],
                'new_train_count': len(new_train), 'new_validation_count': len(new_val),
                'parent_release': parent_release, 'final_test_status': 'pending_fresh_field_photos', 'files': {}}
    for name, selected in (('train', all_train), ('validation', all_val)):
        for row in selected:
            row.update(split_name=name, data_version=version)
        path = split_dir / (name + '.csv')
        write_csv(path, selected, fields=EVOLUTION_FIELDS)
        metadata['files'][name] = {'count': len(selected), 'sha256': digest(path), 'counts': dict(Counter(r['category_id'] for r in selected))}
    write_json(split_dir / 'dataset.json', metadata)
    write_json(ROOT / 'ml/configs/generated' / (version + '.json'), config)
    return metadata


def compare(release, baseline='campus-gpu-v1'):
    from .release import verify
    from .inference import LiteRunner
    from .training import metrics, prepare
    import numpy as np
    release = Path(release)
    verify(release)
    old_dir = ROOT / 'models/releases' / safe_name(baseline)
    verify(old_dir)
    old, candidate = LiteRunner(old_dir), LiteRunner(release)
    lineage=candidate.metadata.get('parent_lineage',{})
    visited=set()
    while lineage.get('model_sha256')!=old.metadata['sha256']:
        parent_version=lineage.get('model_version')
        if not parent_version or parent_version in visited:
            raise ValueError('Candidate ancestry does not include the fixed baseline')
        visited.add(parent_version)
        parent=read_json(ROOT/'models/releases'/safe_name(parent_version)/'metadata.json')
        if parent['status']!='frozen' or parent['sha256']!=lineage['model_sha256']:
            raise ValueError('Ancestor model identity changed')
        lineage=parent.get('parent_lineage',{})
    if candidate.metadata['status']!='frozen':
        raise ValueError('Candidate must be frozen')
    rows, data = load_split(candidate.metadata['data_version'], 'validation')
    if data.get('purpose') != 'evolution_development' or data['parent_release'] != candidate.metadata['parent_lineage']['model_version']:
        raise ValueError('Evolution development split and matching baseline required')
    legacy, _ = load_split(old.metadata['data_version'], 'validation')
    legacy_ids = {r['sample_id'] for r in legacy}
    subsets = {'original_public_validation': [r for r in rows if r['sample_id'] in legacy_ids],
               'new_public_development_validation': [r for r in rows if r['sample_id'] not in legacy_ids and r.get('source_dataset') in ('wikimedia_commons', 'open_images')],
               'field_development_validation': [r for r in rows if r.get('source_dataset') in ('field', 'self_captured')]}
    if {r['sample_id'] for r in subsets['original_public_validation']} != legacy_ids:
        raise ValueError('Original baseline validation membership changed')
    report = {'purpose': 'evolution_comparison', 'status': 'pending_human_approval', 'created_at': now(),
              'baseline': old.metadata, 'candidate': candidate.metadata, 'data_metadata_sha256': digest(ROOT / 'data/splits' / data['data_version'] / 'dataset.json'),
              'test_images_read': False, 'subsets': {}, 'warnings': []}
    for name, selected in subsets.items():
        if not selected:
            report['warnings'].append(name + ': no samples; field improvement has not been established')
            continue
        x, y = prepare(selected)
        labels = sorted(set(map(int, y)))
        report['subsets'][name] = {'count': len(selected), 'present_category_ids': labels,
                                  'baseline': metrics(y, np.stack([old.predict_tensor(a) for a in x])),
                                  'candidate': metrics(y, np.stack([candidate.predict_tensor(a) for a in x]))}
    path = ROOT / 'experiments/reports/evolution' / (candidate.metadata['model_version'] + '-comparison.json')
    if path.exists():
        raise ValueError('Comparison exists; evidence is immutable')
    write_json(path, report)
    return path


def accept_approval(release, receipt_path, comparison_path):
    """Attach the admin's downloaded decision without changing frozen model files."""
    from .release import verify
    release=Path(release)
    verify(release)
    metadata=read_json(release/'metadata.json')
    receipt=read_json(receipt_path)
    report=read_json(comparison_path)
    if receipt.get('status')!='approved' or receipt.get('model_sha256')!=metadata['sha256'] or receipt.get('model_version')!=metadata['model_version'] or receipt.get('report_sha256')!=digest(comparison_path) or report['candidate']['sha256']!=metadata['sha256']:
        raise ValueError('Approval/report/model identities differ')
    if not all(receipt.get(k) for k in ('approved_by','approved_at','reason')):
        raise ValueError('Human approval identity/reason missing')
    destination=release/'approval.json'
    if destination.exists():
        if read_json(destination)!=receipt:
            raise ValueError('Approval receipt already exists with different content')
    else:
        write_json(destination,receipt)
    return receipt
