"""Confirm a Git commit contains the exact training module bytes used locally."""
import argparse
import hashlib
import subprocess
from pathlib import Path

from recognition.common import ROOT, now, write_json
from recognition.training import snapshot

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--commit', default='HEAD')
parser.add_argument('--out', type=Path, default=ROOT/'experiments/reports/environment/implementation-source.json')
args = parser.parse_args()
commit = subprocess.check_output(['git', 'rev-parse', args.commit], cwd=ROOT, text=True).strip()
identity = hashlib.sha256()
rows = []
for path in sorted((ROOT/'ml/src/recognition').glob('*.py')):
    name = path.relative_to(ROOT).as_posix()
    committed = subprocess.check_output(['git', 'show', commit+':'+name], cwd=ROOT)
    identity.update(path.name.encode())
    identity.update(committed)
    rows.append({'file': name, 'matches_committed_bytes': committed == path.read_bytes()})
if not all(row['matches_committed_bytes'] for row in rows) or identity.hexdigest() != snapshot():
    raise SystemExit('Commit and working training modules differ; do not assert reproducibility')
record = {
    'at': now(), 'implementation_commit': commit,
    'committed_code_snapshot_sha256': identity.hexdigest(),
    'working_code_snapshot_sha256': snapshot(), 'all_module_bytes_match': True,
    'modules': rows,
    'note': 'Runs preserve their start HEAD and exact source archive; this commit contains these module bytes.',
}
write_json(args.out, record)
print(args.out)
