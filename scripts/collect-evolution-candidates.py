"""Resume a bounded public-photo expansion without replaying old candidates."""
import argparse
import collections
import os
import shlex
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--state', type=Path, required=True)
parser.add_argument('--stop-after', type=int, choices=(500, 2000), default=500)
parser.add_argument('--remote-fetch', choices=('tencent',), help='Fetch bounded official image URLs through the existing SSH host')
args = parser.parse_args()
os.environ['RECOGNITION_ROOT'] = str(args.root.resolve())
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ml/src'))
from recognition import collect
from recognition.common import ROOT, read_csv, read_json, write_csv, write_json, now

targets = {'charger': 350, 'key': 350, 'umbrella': 250, 'earphones': 250, 'mouse': 200,
           'pencil_case': 120, 'book': 120, 'cup': 120, 'keyboard': 120, 'backpack': 120}
mapping = {c['label_key']: str(c['id']) for c in collect.categories()['categories']}
if args.remote_fetch:
    def remote_fetch(url, limit, retries=3):
        # Only fixed dataset origins; no general-purpose public proxy or port.
        code = '''import sys, urllib.request, urllib.parse
url, limit = sys.argv[1], int(sys.argv[2])
if urllib.parse.urlsplit(url).scheme != 'https' or urllib.parse.urlsplit(url).hostname not in ('commons.wikimedia.org', 'upload.wikimedia.org', 'open-images-dataset.s3.amazonaws.com'):
    raise ValueError('Unsupported collection origin')
with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'CampusRecognitionCourse/0.1 (educational image classification; attribution retained)'}), timeout=30) as r:
    if int(r.headers.get('Content-Length', '0')) > limit: raise ValueError('Response exceeds byte limit')
    data = r.read(limit + 1)
    if len(data) > limit: raise ValueError('Response exceeds byte limit')
    sys.stdout.buffer.write(data)
'''
        command = 'python3 -c ' + shlex.quote(code) + ' ' + shlex.quote(url) + ' ' + str(limit)
        for attempt in range(retries):
            result = subprocess.run(['ssh', args.remote_fetch, command], capture_output=True, timeout=45)
            if result.returncode == 0:
                if len(result.stdout) > limit:
                    raise ValueError('Response exceeds byte limit')
                return result.stdout
            if attempt == retries - 1:
                raise ValueError('Official-source fetch failed: ' + result.stderr.decode(errors='replace').splitlines()[-1][:160])
            __import__('time').sleep(2 ** (attempt + 1))
    collect.fetch = remote_fetch


def manifests():
    return [r for name in ('public-candidates.csv', 'openimages-candidates.csv')
            for r in read_csv(ROOT / 'data/manifests' / name)]


args.state.parent.mkdir(parents=True, exist_ok=True)
if args.state.exists():
    state = read_json(args.state)
    if state['root'] != str(ROOT) or state['targets'] != targets:
        raise ValueError('Expansion identity differs; keep the original round state')
else:
    previous = manifests()
    state = {'purpose': 'bounded_public_expansion', 'root': str(ROOT), 'started_at': now(),
             'max_new': 2000, 'class_cap': 750, 'photo_budget_bytes': collect.PHOTO_BUDGET,
             'targets': targets, 'previous_ids': [r['sample_id'] for r in previous],
             'previous_hashes': sorted({r['image_sha256'] for r in previous})}
    write_json(args.state, state)


def progress():
    old_ids, old_hashes = set(state['previous_ids']), set(state['previous_hashes'])
    unique = {}
    for row in manifests():
        if row['sample_id'] not in old_ids and row['image_sha256'] not in old_hashes:
            unique.setdefault(row['image_sha256'], row)
    rows = list(unique.values())
    state.update(updated_at=now(), downloaded=len(rows),
                 by_category=dict(collections.Counter(r['category_id'] for r in rows)),
                 raw_bytes=sum(p.stat().st_size for provider in ('commons', 'openimages')
                               for p in (ROOT / 'data/raw' / provider).rglob('*') if p.is_file()))
    write_csv(args.state.with_suffix('.csv'), rows)
    write_json(args.state, state)
    return rows


for provider in ('commons', 'openimages'):
    for key, total_target in targets.items():
        current = progress()
        remaining = args.stop_after - len(current)
        if remaining <= 0 or state['raw_bytes'] >= collect.PHOTO_BUDGET:
            break
        if provider == 'openimages' and key not in collect.MIDS:
            continue
        desired = total_target if args.stop_after == 2000 else max(1, total_target // 4) + int(key in ('charger', 'key'))
        needed = min(remaining, desired - sum(r['category_id'] == mapping[key] for r in current))
        if needed <= 0:
            continue
        source_name = 'public-candidates.csv' if provider == 'commons' else 'openimages-candidates.csv'
        source_rows = read_csv(ROOT / 'data/manifests' / source_name)
        source_count = sum(r['category_id'] == mapping[key] for r in source_rows)
        target = min(750, source_count + needed)
        print(f'{provider} {key}: request up to {needed} new photos; round {len(current)}/{args.stop_after}', flush=True)
        if provider == 'commons':
            collect.collect_commons([key], target, class_cap=750, max_new=needed)
        else:
            # The already-scanned train index is never downloaded again.
            collect.collect_openimages([key], target, 'validation', class_cap=750, max_new=needed)
            progress()
            left = min(args.stop_after - state['downloaded'],
                       desired - state['by_category'].get(mapping[key], 0))
            if left > 0:
                source_count = sum(r['category_id'] == mapping[key] for r in read_csv(ROOT / 'data/manifests' / source_name))
                collect.collect_openimages([key], min(750, source_count + left), 'public-test', class_cap=750, max_new=left)
        progress()
state.update(state='checkpoint' if state['downloaded'] >= args.stop_after else 'source_gap', checkpoint=args.stop_after)
progress()
print({key: state[key] for key in ('state', 'downloaded', 'by_category', 'raw_bytes')}, flush=True)
