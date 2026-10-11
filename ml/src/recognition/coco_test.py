"""A held-out COCO/field classification test, isolated from training queues."""
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import random
import struct
import urllib.request
import zlib

from PIL import Image, ImageDraw

from .common import ROOT, FIELDS, categories, category_path, digest, image_path, now, read_csv, read_json, safe_name, write_csv, write_json
from .data import check_isolation, identity_keys, perceptual_keys, phash

PURPOSE = 'mixed_coco_field_test'
CATEGORY_VERSION = 'campus-10-v4'
COCO_IDS = {0: 47, 1: 28, 2: 84, 4: 74, 5: 76, 9: 27}
FIELD_IDS = {3, 6, 7, 8}
EXTRA_FIELDS = ['source_sample_id', 'parent_image_sha256', 'parent_phash', 'crop_box']
ANNOTATION_SHA256 = 'e8c7f7908f1d7278341fae127d0da654f102f11bd7b21d8aeefa635b8c810b6f'
ANNOTATION_URL = 'https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip'
MIN_SIDE, MIN_AREA, MARGIN = 48, .01, .05


def download(url, limit, byte_range=None):
    headers = {'User-Agent': 'CampusRecognitionCourse/0.1 (held-out evaluation)'}
    if byte_range:
        headers['Range'] = 'bytes=' + byte_range
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as response:
        if byte_range and (response.status != 206 or not response.headers.get('Content-Range', '').startswith('bytes ' + byte_range + '/')):
            raise ValueError('Official storage did not honor the bounded byte range')
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError('COCO download exceeds byte budget')
    return body


def annotations(path=None):
    path = Path(path) if path else ROOT / 'data/raw/coco2017/instances_val2017.json'
    if not path.exists():
        # Pinned official ZIP member: fetch only the local header and 6.53 MB
        # deflated validation JSON, never the 252 MB training annotation archive.
        start, compressed, size = 152757923, 6529031, 19987840
        end = start + 30 + len('annotations/instances_val2017.json') + 65535 + compressed - 1
        body = download(ANNOTATION_URL, end - start + 1, f'{start}-{end}')
        header = struct.unpack_from('<4s5H3I2H', body)
        if header[0] != b'PK\x03\x04' or header[3] != 8:
            raise ValueError('Unexpected official annotation ZIP member')
        offset = 30 + header[-2] + header[-1]
        if body[30:30 + header[-2]] != b'annotations/instances_val2017.json':
            raise ValueError('Unexpected annotation filename')
        decoder = zlib.decompressobj(-15)
        raw = decoder.decompress(body[offset:offset + compressed], size + 1)
        if not decoder.eof or len(raw) != size or zlib.crc32(raw) != 781945669 or hashlib.sha256(raw).hexdigest() != ANNOTATION_SHA256:
            raise ValueError('Official validation annotation integrity check failed')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp'); temporary.write_bytes(raw); temporary.replace(path)
    if digest(path) != ANNOTATION_SHA256:
        raise ValueError('COCO validation annotation hash differs from pinned source')
    return read_json(path)


def eligible_annotations(value):
    images = {r['id']: r for r in value['images']}
    expected = {coco_id: categories(CATEGORY_VERSION)['categories'][category]['label_key'] for category, coco_id in COCO_IDS.items()}
    actual = {r['id']: r['name'] for r in value['categories']}
    if any(actual.get(key) != name for key, name in expected.items()):
        raise ValueError('COCO category mapping differs')
    found = {category: [] for category in COCO_IDS}
    for ann in value['annotations']:
        if ann['category_id'] not in expected or ann.get('iscrowd'):
            continue
        image = images[ann['image_id']]
        x, y, width, height = ann['bbox']
        if not all(math.isfinite(v) for v in (x, y, width, height)) or min(width, height) < MIN_SIDE:
            continue
        if width * height / (image['width'] * image['height']) < MIN_AREA:
            continue
        category = next(key for key, val in COCO_IDS.items() if val == ann['category_id'])
        found[category].append((ann, image))
    return found


def overlaps(row, previous):
    keys, hashes = identity_keys(row), perceptual_keys(row)
    return any(keys & identity_keys(other) or any((a ^ b).bit_count() <= 6 for a in hashes for b in perceptual_keys(other)) for other in previous)


def reviewed_selection(reservation, reviewed_manifest):
    safe_name(reservation)
    directory=ROOT/'data/test-reservations'/reservation
    metadata=read_json(directory/'reservation.json')
    if digest(directory/'samples.csv')!=metadata['manifest_sha256']:
        raise ValueError('Reserved COCO identities changed')
    expected={r['sample_id']:r for r in read_csv(directory/'samples.csv')}
    reviewed=read_csv(reviewed_manifest)
    if set(expected)!={r['sample_id'] for r in reviewed} or len(reviewed)!=len(expected):
        raise ValueError('Reviewed COCO selection differs from reserved test')
    for row in reviewed:
        if any(row.get(key,'')!=expected[row['sample_id']].get(key,'') for key in FIELDS+EXTRA_FIELDS if key not in ('review_status','review_reason')):
            raise ValueError('Only visual approval/reason may change after COCO reservation')
    return reviewed,metadata


def prepare(version, per_class=20, seed=42, annotation_file=None, replace_reservation=None, reviewed_manifest=None):
    safe_name(version)
    if per_class != 20:
        raise ValueError('Initial test protocol fixes twenty distinct source photos per class')
    directory = ROOT / 'data/test-reservations' / version
    if directory.exists():
        raise ValueError('Test reservation exists; preserve its identities and protocol')
    value = annotations(annotation_file)
    candidates = eligible_annotations(value)
    previous = []
    for path in (ROOT / 'data/manifests').glob('*.csv'):
        previous.extend(read_csv(path))
    for path in (ROOT / 'data/splits').glob('*/train.csv'):
        previous.extend(read_csv(path))
    for path in (ROOT / 'data/splits').glob('*/validation.csv'):
        previous.extend(read_csv(path))
    for path in (ROOT / 'data/test-reservations').glob('*/samples.csv'):
        previous.extend(read_csv(path))
    rng = random.Random(seed)
    selected, used_images, skipped = [], set(), Counter()
    lineage={}
    if bool(replace_reservation)!=bool(reviewed_manifest):
        raise ValueError('Replacement requires both the previous reservation and reviewed manifest')
    if replace_reservation:
        reviewed,parent=reviewed_selection(replace_reservation,reviewed_manifest)
        if parent['protocol']!={'per_class':per_class,'min_bbox_side':MIN_SIDE,'min_bbox_area_ratio':MIN_AREA,
                               'bbox_margin_ratio':MARGIN,'one_crop_per_source_image':True,
                               'selection_uses_predictions':False,'resize_or_upscale_before_crop':False} or parent['seed']!=seed:
            raise ValueError('Replacement cannot change the original sampling protocol')
        if any(r['review_status'] not in ('approved','rejected') or not r.get('review_reason') for r in reviewed):
            raise ValueError('Finish visual review with reasons before replacement')
        from .release import tested_image_hashes
        protected={r['image_sha256'] for r in reviewed}|{r['parent_image_sha256'] for r in reviewed}
        if any(protected & tested_image_hashes(read_json(path)) for path in (ROOT/'experiments/reports/evaluations').glob('*/*-test.json')):
            raise ValueError('Cannot replace samples after model testing')
        selected=[{**r,'data_version':version} for r in reviewed if r['review_status']=='approved']
        used_images={int(r['source_id']) for r in selected}
        lineage={'parent_reservation':replace_reservation,'visual_decisions_sha256':digest(reviewed_manifest),
                 'rejected_sample_ids':[r['sample_id'] for r in reviewed if r['review_status']=='rejected']}
    license_by_id = {r['id']: r for r in value['licenses']}
    photo_bytes = sum(p.stat().st_size for p in (ROOT / 'data/raw').rglob('*') if p.is_file())
    downloaded_bytes = 0
    # Scarce classes first; one original image may contribute only one sample.
    for category in sorted(candidates, key=lambda c: (len(candidates[c]), c)):
        options = sorted(candidates[category], key=lambda pair: pair[0]['id']); rng.shuffle(options)
        count = sum(int(r['category_id'])==category for r in selected)
        for ann, info in options:
            if count == per_class:
                break
            if info['id'] in used_images:
                continue
            filename = info['file_name']
            if filename != f"{info['id']:012d}.jpg":
                raise ValueError('Unexpected COCO source filename')
            url = 'https://s3.amazonaws.com/images.cocodataset.org/val2017/' + filename
            original = ROOT / 'data/raw/coco2017/val2017' / filename
            if not original.exists():
                if downloaded_bytes + 5 * 1024**2 > 128 * 1024**2 or photo_bytes + 5 * 1024**2 > 3 * 1024**3:
                    raise ValueError('COCO test photo download budget reached')
                blob = download(url, 5 * 1024**2)
                downloaded_bytes += len(blob); photo_bytes += len(blob)
                original.parent.mkdir(parents=True, exist_ok=True); original.write_bytes(blob)
            with Image.open(original) as image:
                image.load()
                if image.size != (info['width'], info['height']):
                    raise ValueError('COCO source dimensions differ from annotations')
                x, y, width, height = ann['bbox']
                box = [max(0, math.floor(x - width * MARGIN)), max(0, math.floor(y - height * MARGIN)),
                       min(image.width, math.ceil(x + width * (1 + MARGIN))), min(image.height, math.ceil(y + height * (1 + MARGIN)))]
                crop = image.crop(box).convert('RGB')
                parent_hash = phash(image)
            output = io.BytesIO(); crop.save(output, format='PNG'); cropped = output.getvalue()
            row = {'sample_id': f"coco2017-{info['id']:012d}-ann-{ann['id']}",
                   'image_sha256': hashlib.sha256(cropped).hexdigest(), 'category_id': str(category),
                   'source_dataset': 'coco2017_val', 'source_id': str(info['id']),
                   'source_sample_id': f"coco2017-{info['id']:012d}", 'group_id': f"coco2017-image-{info['id']}",
                   'session_id': 'coco2017-val', 'collector': 'official-coco-annotations',
                   'split_name': 'test', 'review_status': 'pending', 'data_version': version,
                   'source_url': info.get('flickr_url', ''), 'original_url': info.get('flickr_url', '') or info['coco_url'],
                   'download_url': url, 'license': license_by_id[info['license']]['name'],
                   'license_url': license_by_id[info['license']]['url'], 'author': '',
                   'source_version': 'COCO2017 val; instances SHA256=' + ANNOTATION_SHA256,
                   'downloaded_at': now(), 'width': str(crop.width), 'height': str(crop.height),
                   'parent_image_sha256': digest(original), 'parent_phash': parent_hash,
                   'phash': phash(crop), 'crop_box': json.dumps(box)}
            if overlaps(row, previous + selected):
                skipped['training_or_near_duplicate'] += 1; continue
            destination = ROOT / 'data/processed/coco-test' / version / (row['sample_id'] + '.png')
            if photo_bytes + len(cropped) > 3 * 1024**3:
                raise ValueError('Total raw and test crop budget reached')
            destination.parent.mkdir(parents=True, exist_ok=True); destination.write_bytes(cropped)
            photo_bytes += len(cropped)
            row['image_path'] = destination.relative_to(ROOT).as_posix()
            selected.append(row); used_images.add(info['id']); count += 1
        skipped[f'class_{category}_shortfall'] = max(0, per_class - count)
    selected.sort(key=lambda r: (int(r['category_id']), r['sample_id']))
    write_csv(directory / 'samples.csv', selected, FIELDS + EXTRA_FIELDS)
    category = categories(CATEGORY_VERSION)
    metadata = {'purpose': PURPOSE, 'status': 'reserved_pending_visual_review_and_field_photos', 'version': version,
                'category_version': category['category_version'], 'categories_sha256': digest(category_path(CATEGORY_VERSION)),
                'manifest_sha256': digest(directory / 'samples.csv'), 'created_at': now(), 'seed': seed,
                'annotation_sha256': ANNOTATION_SHA256, 'annotation_url': ANNOTATION_URL,
                'protocol': {'per_class': per_class, 'min_bbox_side': MIN_SIDE, 'min_bbox_area_ratio': MIN_AREA,
                             'bbox_margin_ratio': MARGIN, 'one_crop_per_source_image': True,
                             'selection_uses_predictions': False, 'resize_or_upscale_before_crop': False},
                'counts': dict(Counter(r['category_id'] for r in selected)), 'skipped': dict(skipped),
                'field_classes_required': sorted(FIELD_IDS), 'downloaded_photo_bytes': downloaded_bytes,
                'training_prohibited': True, 'independent_phone_acceptance': False}
    metadata.update(lineage)
    write_json(directory / 'reservation.json', metadata)
    write_csv(directory / 'field-template.csv', [], FIELDS)
    for category in COCO_IDS:
        rows = [r for r in selected if int(r['category_id']) == category]
        sheet = Image.new('RGB', (1000, 225 * math.ceil(max(1, len(rows)) / 5)), 'white')
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(rows):
            x, y = index % 5 * 200, index // 5 * 225
            with Image.open(image_path(row['image_path'])) as image:
                image.thumbnail((190, 180)); sheet.paste(image, (x, y))
            draw.text((x + 2, y + 183), row['sample_id'].replace('coco2017-', ''), fill='black')
        path = ROOT / 'data/processed/coco-test' / version / f'class-{category}-contact.jpg'
        path.parent.mkdir(parents=True, exist_ok=True); sheet.save(path)
    return metadata


def validate_mixed_rows(rows):
    if len(rows) != 200 or any(sum(int(r['category_id']) == category for r in rows) != 20 for category in range(10)):
        raise ValueError('Mixed test requires exactly twenty approved photos in each of ten classes')
    if len({r['sample_id'] for r in rows}) != len(rows) or len({r['image_sha256'] for r in rows}) != len(rows):
        raise ValueError('Duplicate mixed test sample identity')
    coco_images = set()
    for row in rows:
        category = int(row['category_id'])
        if row.get('review_status') != 'approved':
            raise ValueError('All mixed test photos require visual approval')
        if category in COCO_IDS:
            if row.get('source_dataset') != 'coco2017_val' or not row.get('parent_image_sha256') or not row.get('crop_box'):
                raise ValueError('COCO classes require original identities and official-box crops')
            if row.get('source_id') in coco_images:
                raise ValueError('Only one crop per COCO source image is allowed')
            coco_images.add(row.get('source_id'))
        elif row.get('source_dataset') not in ('field', 'self_captured') or not row.get('object_id') or not row.get('session_id'):
            raise ValueError('Missing classes require field photos, object IDs and capture sessions')


def freeze(version, reservation, reviewed_manifest, field_manifest, training_version):
    from .data import load_split
    safe_name(version); safe_name(reservation)
    directory = ROOT / 'data/splits' / version
    if directory.exists():
        raise ValueError('Test version exists; do not overwrite frozen tests')
    reserved_dir = ROOT / 'data/test-reservations' / reservation
    coco_rows,info=reviewed_selection(reservation,reviewed_manifest)
    field_rows=read_csv(field_manifest)
    for row in field_rows:
        for key in ('object_id','group_id','session_id'):
            row[key]=row.get(key,'').strip()
    rows = coco_rows + field_rows
    validate_mixed_rows(rows)
    train, data = load_split(training_version, 'train'); validation, _ = load_split(training_version, 'validation')
    if data['category_version'] != info['category_version'] or data['categories_sha256'] != info['categories_sha256']:
        raise ValueError('Mixed test must use the reserved category scope')
    for row in rows:
        if digest(image_path(row['image_path'])) != row['image_sha256']:
            raise ValueError('Mixed test image hash differs')
        with Image.open(image_path(row['image_path'])) as image:
            image.load()
            if int(row['category_id']) in FIELD_IDS and min(image.size)<128:
                raise ValueError('Field test photo is too small')
            row['phash']=phash(image)
            row['width'],row['height']=map(str,image.size)
        row.update(split_name='test', data_version=version)
    check_isolation(train, validation, rows)
    write_csv(directory / 'test.csv', rows, FIELDS + EXTRA_FIELDS)
    metadata = {'status': 'frozen', 'purpose': PURPOSE, 'data_version': version, 'training_version': training_version,
                'category_version': data['category_version'], 'categories_sha256': data['categories_sha256'],
                'created_at': now(), 'reservation': reservation, 'protocol': info['protocol'],
                'independent_phone_acceptance': False,
                'files': {'test': {'sha256': digest(directory / 'test.csv'), 'count': len(rows)}}}
    write_json(directory / 'dataset.json', metadata)
    return metadata
