"""Bounded official Caltech101 auxiliary data; class-disjoint OOD development splits."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import tarfile
import time
import urllib.request
import zipfile
from PIL import Image, ImageOps

SOURCE = 'https://data.caltech.edu/records/mzrjq-6wc02'
MD5 = '3138e1922a9193bfa496528edbbc45d0'
LIMIT = 180 * 1024 * 1024
CLASSES = {
    'train': ['airplanes', 'ant', 'beaver', 'binocular', 'bonsai', 'butterfly', 'camera', 'cannon',
              'car_side', 'ceiling_fan', 'cellphone', 'chair', 'chandelier', 'crab', 'crayfish',
              'dalmatian', 'dolphin', 'dragonfly', 'electric_guitar', 'elephant', 'emu', 'euphonium',
              'ferry', 'flamingo', 'gerenuk', 'gramophone', 'helicopter', 'ibis', 'inline_skate', 'kangaroo'],
    'calibration': ['joshua_tree', 'ketch', 'lamp', 'llama', 'lobster', 'lotus', 'mandolin', 'mayfly', 'menorah', 'metronome'],
    'holdout': ['crocodile', 'crocodile_head', 'hawksbill', 'leopards', 'cougar_body', 'cougar_face',
                'wild_cat', 'scissors', 'stapler', 'wrench'],
}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--known-data-root', required=True, type=Path)
parser.add_argument('--source', choices=['official', 'fastai'], default='official')
parser.add_argument('--preset', choices=['v1', 'v2'], default='v1')
parser.add_argument('--archive', type=Path)
args = parser.parse_args()
if args.preset == 'v2':
    CLASSES['train'] = CLASSES['train'] + CLASSES['holdout']
    CLASSES['holdout'] = ['octopus', 'okapi', 'panda', 'pigeon', 'pizza', 'platypus', 'rhino', 'rooster',
                          'scorpion', 'sea_horse', 'starfish', 'stegosaurus', 'stop_sign', 'strawberry',
                          'sunflower', 'tick', 'watch', 'wheelchair', 'windsor_chair', 'nautilus']
args.output.mkdir(parents=True, exist_ok=True)
if (args.output / 'metadata.json').exists():
    raise ValueError('Dataset version already frozen')
download_url = (SOURCE + '/files/caltech-101.zip?download=1&cache_bust=' + str(int(time.time()))
                if args.source == 'official' else 'https://s3.amazonaws.com/fast-ai-imageclas/caltech_101.tgz')
archive = args.archive or args.output / ('caltech-101.zip' if args.source == 'official' else 'caltech_101.tgz')
if not archive.exists():
    request = urllib.request.Request(download_url,
                                     headers={'User-Agent': 'CampusRecognitionAcademicExperiment/1.0', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=60) as response, archive.with_suffix('.part').open('wb') as target:
        if int(response.headers.get('Content-Length', '0')) > LIMIT:
            raise ValueError('Download exceeds declared 180 MiB limit')
        size = 0
        while chunk := response.read(1024*1024):
            size += len(chunk)
            if size > LIMIT:
                raise ValueError('Download limit reached')
            target.write(chunk)
            if size % (20 * 1024 * 1024) < 1024 * 1024:
                print('Downloaded MiB:', size//1024//1024, flush=True)
    archive.with_suffix('.part').replace(archive)
blob = archive.read_bytes()
archive_md5 = hashlib.md5(blob).hexdigest()
if len(blob) > LIMIT or (args.source == 'official' and archive_md5 != MD5):
    raise ValueError('Official archive checksum differs')
excluded_hashes = set()
for folder in ['splits', 'test-reservations', 'manifests']:
    for manifest in (args.known_data_root / 'data' / folder).rglob('*.csv'):
        with manifest.open(encoding='utf-8-sig', newline='') as handle:
            excluded_hashes.update(row['image_sha256'] for row in csv.DictReader(handle) if row.get('image_sha256'))
if args.source == 'official':
    with zipfile.ZipFile(io.BytesIO(blob)) as source:
        members = [member for member in source.infolist() if member.filename.endswith('/101_ObjectCategories.tar.gz') or member.filename == '101_ObjectCategories.tar.gz']
        if len(members) != 1 or members[0].file_size > LIMIT:
            raise ValueError('Unexpected official archive layout')
        image_archive = source.read(members[0])
else:
    image_archive = blob
rows = []
seen_hashes = set(excluded_hashes)
seen_visual = []
by_class = {}
payloads = {}
requested_classes = {category for values in CLASSES.values() for category in values}
with tarfile.open(fileobj=io.BytesIO(image_archive), mode='r|gz') as source:
    for item in source:
        parts = Path(item.name).parts
        if (item.isfile() and len(parts) >= 3 and parts[-1].lower().endswith('.jpg') and '..' not in parts
                and parts[-2].casefold() in requested_classes and item.size <= 5*1024*1024):
            by_class.setdefault(parts[-2].casefold(), []).append(item)
            payloads[item.name] = source.extractfile(item).read()
    missing = set(category for values in CLASSES.values() for category in values) - by_class.keys()
    if missing:
        raise ValueError('Missing declared source categories: ' + ', '.join(sorted(missing)))
    for split, classes in CLASSES.items():
        for category in classes:
            if category not in by_class:
                raise ValueError('Missing declared source category: ' + category)
            candidates = sorted(by_class[category], key=lambda item: item.name)
            random.Random('scope-data-v1/' + category).shuffle(candidates)
            count = 0
            for item in candidates:
                if item.size > 5*1024*1024:
                    continue
                content = payloads[item.name]
                image_hash = hashlib.sha256(content).hexdigest()
                if image_hash in seen_hashes:
                    continue
                try:
                    with Image.open(io.BytesIO(content)) as original:
                        original.load()
                        if min(original.size) < 64:
                            continue
                        gray = ImageOps.exif_transpose(original).convert('L').resize((9, 8), Image.Resampling.BILINEAR)
                        pixels = list(gray.tobytes())
                        visual = sum((pixels[y*9+x] > pixels[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
                except (OSError, ValueError):
                    continue
                if any((visual ^ previous).bit_count() <= 4 for previous in seen_visual):
                    continue
                relative = Path('images') / category / Path(item.name).name
                destination = args.output / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                seen_hashes.add(image_hash); seen_visual.append(visual)
                rows.append({'sample_id': 'caltech101-' + category + '-' + Path(item.name).stem,
                             'image_path': relative.as_posix(), 'image_sha256': image_hash, 'split': split,
                             'scope_target': 0, 'semantic_class': category, 'group_id': 'caltech101-' + category,
                             'source': SOURCE, 'source_archive_md5': archive_md5, 'dhash': f'{visual:016x}'})
                count += 1
                if count >= (30 if split == 'train' else 20):
                    break
            if count < 10:
                raise ValueError('Insufficient nonduplicate samples: ' + category)
            print(split, category, count, flush=True)
manifest = args.output / 'samples.csv'
with manifest.open('w', newline='', encoding='utf-8') as target:
    writer = csv.DictWriter(target, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
metadata = {'data_version': 'scope-aux-caltech101-' + args.preset, 'seed': 'scope-data-v1/<semantic_class>',
            'source': SOURCE, 'source_doi': '10.22002/D1.20086',
            'license': 'Not specified on the source record; original photos are kept local and not redistributed.',
            'download_source': download_url, 'mirror_provider': None if args.source == 'official' else 'fastai',
            'source_archive_sha256': hashlib.sha256(blob).hexdigest(), 'source_archive_md5': archive_md5,
            'source_archive_bytes': len(blob), 'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'classes': CLASSES, 'counts': {split: sum(row['split'] == split for row in rows) for split in CLASSES},
            'selection': 'Predeclared non-target source classes; source labels are dataset annotations, not Qwen labels.',
            'excluded_known_and_test_manifest_hashes': len(excluded_hashes),
            'known_target_classes_excluded': ['cup', 'umbrella', 'headphone', 'laptop', 'backpack', 'BACKGROUND_Google'],
            'semantic_class_disjoint': True, 'exact_duplicates_removed': True,
            'previous_development_holdout_demoted_to_training': 'scope-aux-caltech101-v1' if args.preset == 'v2' else None,
            'approximate_duplicate_check': '64-bit dHash, distance <=4; cannot prove physical-object isolation.',
            'holdout_used_for_training_or_selection': False, 'protected_project_test_images_read': False,
            'limitations': ['A public auxiliary benchmark does not establish real phone OOD performance.',
                            'Source categories and approximate hashing do not guarantee original-object identity.']}
(args.output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
print(json.dumps(metadata['counts']), flush=True)
