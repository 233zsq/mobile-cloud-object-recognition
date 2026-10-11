"""Package only review source and public baseline metadata; no photos/secrets."""
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
output = root / 'tmp/campus-review-source.tar.gz'
output.parent.mkdir(exist_ok=True)
files = [p for p in (root / 'review').rglob('*') if p.is_file() and not any(
    part in ('.venv', 'var', '__pycache__', '.pytest_cache') for part in p.relative_to(root).parts)]
files += [root / 'shared/categories.json', root / 'models/releases/campus-gpu-v1/metadata.json',
          root / 'shared/category-versions/campus-10-v3.json',
          root / 'shared/category-versions/campus-10-v4.json',
          root / 'models/releases/campus-gpu-v1/evaluation-validation.json']
identity = {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True)),
            'files': {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}}
receipt = root / 'tmp/SOURCE.json'
receipt.write_text(json.dumps(identity, indent=2) + '\n', encoding='utf-8')
with tarfile.open(output, 'w:gz') as archive:
    for path in sorted(files):
        archive.add(path, path.relative_to(root).as_posix())
    archive.add(receipt, 'SOURCE.json')
print(hashlib.sha256(output.read_bytes()).hexdigest(), output)
