"""Package cached public candidates, excluding all frozen dataset sample/hash IDs."""
import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campus_review.assets import source_metadata

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--manifest', type=Path, help='Package only this increment, rather than all cached candidates')
parser.add_argument('--exclude', type=Path, help='CSV of previously reviewed sample_id/image_sha256, including rejections')
args = parser.parse_args()
root = args.root.resolve()
used_ids, used_hashes = set(), set()
if args.exclude:
    with args.exclude.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            used_ids.add(row['sample_id']); used_hashes.add(row['image_sha256'])
for manifest in (root / 'data/splits').glob('*/*.csv'):
    if manifest.name not in ('train.csv', 'validation.csv', 'test.csv'):
        continue
    with manifest.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            used_ids.add(row['sample_id']); used_hashes.add(row['image_sha256'])
rows, paths, seen = [], {}, set()
manifests = [args.manifest] if args.manifest else [root / 'data/manifests' / name for name in ('public-reviewed.csv', 'public-candidates.csv', 'openimages-candidates.csv')]
for manifest in manifests:
    with manifest.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['sample_id'] in used_ids or row['image_sha256'] in used_hashes or row['image_sha256'] in seen:
                continue
            path = (root / row['image_path']).resolve()
            if not path.is_relative_to(root / 'data/raw') or not path.is_file() or path.stat().st_size > 8 * 1024**2:
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['image_sha256']:
                raise ValueError('Local photo hash changed: ' + row['sample_id'])
            meta = source_metadata({**row, 'previous_review_reason': row.get('review_reason', '')})
            target = 'images/' + row['sample_id'] + path.suffix.lower()
            rows.append({**meta, 'sample_id': row['sample_id'], 'image_path': target,
                         'image_sha256': row['image_sha256'], 'category_id': row['category_id'],
                         'object_id': row.get('object_id', ''), 'group_id': row.get('group_id', '')})
            seen.add(row['image_sha256']); paths[target] = path
if not rows:
    raise ValueError('No unused public candidates to package')
stream = io.StringIO(newline='')
writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
writer.writeheader(); writer.writerows(rows)
payload = stream.getvalue().encode()
receipt = {'purpose': 'public_review_queue', 'count': len(rows),
           'categories_sha256': hashlib.sha256((root / 'shared/categories.json').read_bytes()).hexdigest(),
           'files': {'samples.csv': hashlib.sha256(payload).hexdigest(), **{r['image_path']: r['image_sha256'] for r in rows}}}
if sum(p.stat().st_size for p in paths.values()) > 3 * 1024**3 or len(rows) > 3000:
    raise ValueError('Public queue budget exceeded')
args.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_STORED) as package:
    package.writestr('queue.json', json.dumps(receipt)); package.writestr('samples.csv', payload)
    for target, path in paths.items():
        package.write(path, target)
print(json.dumps({'count': len(rows), 'archive_bytes': args.output.stat().st_size,
                  'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))
