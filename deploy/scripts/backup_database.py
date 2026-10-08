"""Root/socket backup of only the application's database; retain seven days."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo; MySQL root uses local socket authentication.")
    directory = Path('/var/backups/mobile-cloud-backend')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.resolve() != directory or directory.stat().st_uid != 0:
        raise SystemExit('Unexpected backup directory.')
    directory.chmod(0o700)
    name = 'object_recognition-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sql.gz'
    destination = directory / name
    try:
        with destination.open('xb') as raw, tempfile.TemporaryFile() as errors:
            destination.chmod(0o600)
            with gzip.GzipFile(fileobj=raw, mode='wb') as output:
                process = subprocess.Popen([
                    '/usr/bin/mysqldump', '--protocol=socket', '--single-transaction',
                    '--no-tablespaces', '--set-gtid-purged=OFF', 'object_recognition',
                ], stdout=subprocess.PIPE, stderr=errors)
                with process.stdout:
                    shutil.copyfileobj(process.stdout, output)
                if process.wait(timeout=300):
                    raise RuntimeError('mysqldump failed; incomplete backup removed.')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    for old in directory.glob('object_recognition-*.sql.gz'):
        if old.is_file() and not old.is_symlink() and time.time() - old.stat().st_mtime > 7 * 86400:
            old.unlink()
    print(json.dumps({'backup': str(destination), 'bytes': destination.stat().st_size,
                      'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
