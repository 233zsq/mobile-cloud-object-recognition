"""Download a verified database backup over host-pinned SSH, without credentials in Git.

Run from the workstation. The destination must be private and excluded from Git.
No server database is changed and no backups are deleted.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--identity', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--backup', required=True, help='Existing /var/backups/mobile-cloud-backend/object_recognition-*.sql.gz')
    parser.add_argument('--sha256', required=True, help='Expected digest from the server backup/restore verification')
    parser.add_argument('--destination', type=Path, required=True, help='Private directory, never a tracked data directory')
    parser.add_argument('--ssh', default='ssh')
    args = parser.parse_args()
    name = Path(args.backup).name
    if args.backup != '/var/backups/mobile-cloud-backend/' + name or not re.fullmatch(r'object_recognition-[0-9TZ]+\.sql\.gz', name):
        raise ValueError('Unexpected managed backup path')
    if not re.fullmatch(r'[0-9a-f]{64}', args.sha256):
        raise ValueError('Expected a lowercase SHA-256 digest')
    identity = args.identity.resolve(strict=True)
    known_hosts = args.known_hosts.resolve(strict=True)
    directory = args.destination.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = directory / name
    receipt = destination.with_name(name + '.json')
    partial = destination.with_name(name + '.partial')
    if any(path.exists() or path.is_symlink() for path in (destination, receipt, partial)):
        raise ValueError('Destination exists; refusing overwrite')
    ssh = [args.ssh, '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
           '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known_hosts),
           '-o', 'GlobalKnownHostsFile=' + ('NUL' if sys.platform == 'win32' else '/dev/null'),
           '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
           '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'KexAlgorithms=curve25519-sha256',
           '-i', str(identity), 'gongyi@49.232.195.47',
           shlex.join(['sudo', '-n', 'cat', args.backup])]
    created = False
    try:
        with partial.open('xb') as stream:
            created = True
            partial.chmod(0o600)
            subprocess.run(ssh, stdout=stream, stderr=subprocess.PIPE, check=True, timeout=120,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        actual = hashlib.sha256(partial.read_bytes()).hexdigest()
        if actual != args.sha256:
            raise ValueError('Downloaded backup digest does not match')
        expanded = 0
        with gzip.open(partial, 'rb') as stream:
            while chunk := stream.read(1024 * 1024):
                expanded += len(chunk)
                if expanded > 512 * 1024 * 1024:
                    raise ValueError('Backup exceeds workstation verification limit')
        partial.rename(destination)
        result = {'backup': str(destination), 'sha256': actual, 'bytes': destination.stat().st_size,
                  'uncompressed_bytes': expanded, 'gzip_integrity_verified': True,
                  'host_key_verification': True, 'server_backup': args.backup}
        with receipt.open('x', encoding='utf-8') as stream:
            receipt.chmod(0o600)
            stream.write(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    finally:
        if created:
            partial.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
