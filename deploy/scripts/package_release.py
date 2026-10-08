"""Archive a fixed Git commit without untracked configuration or credentials."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options',
                                        args.revision + '^{commit}'], cwd=root, text=True).strip()
    output = args.output or root / 'tmp' / ('backend-release-' + revision[:7] + '.tar')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit('Output already exists; choose a new path.')
    subprocess.run(['git', 'archive', '--format=tar', '--output=' + str(output.resolve()), revision], cwd=root, check=True)
    with tarfile.open(output, 'a') as archive:
        content = (revision + '\n').encode()
        entry = tarfile.TarInfo('SOURCE_REVISION')
        entry.size = len(content)
        entry.mode = 0o644
        archive.addfile(entry, io.BytesIO(content))
    print(json.dumps({'archive': str(output), 'source_commit': revision,
                      'archive_sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
