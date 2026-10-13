"""Publish a bounded, hashed static bundle using an atomic directory pointer.

Run with sudo; keeps the previous /ios directory and never touches model or database files.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from deploy.ios_assets import FILES  # noqa: E402

WWW = Path('/var/www/mobile-cloud-ios')
RELEASES = Path('/var/www/mobile-cloud-ios-releases')
SHARED = Path('/home/gongyi/apps/mobile-cloud-backend/shared')
LOCK = Path('/var/lib/campus-review-acme/operation.lock')


def bundle_files(archive, expected):
    if archive.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Static archive exceeds 2 MiB')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError('Static bundle hash differs')
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if {member.name for member in members} != FILES or len(members) != len(FILES):
            raise ValueError('Unexpected static bundle members')
        if any(not member.isfile() or member.size > 1024 * 1024 for member in members):
            raise ValueError('Static bundle contains an unsupported or oversized member')
        return {member.name: source.extractfile(member).read() for member in members}


def publish(archive, expected):
    if archive.resolve().parent != SHARED.resolve():
        raise ValueError('Bundle must be uploaded to the existing shared directory')
    content = bundle_files(archive, expected)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    RELEASES.mkdir(mode=0o755, exist_ok=True)
    release = RELEASES / f'{stamp}-{expected[:12]}'
    release.mkdir(mode=0o755)
    for name, value in content.items():
        target = release / name
        directory = release
        for part in Path(name).parts[:-1]:
            directory /= part
            directory.mkdir(mode=0o755, exist_ok=True)
            directory.chmod(0o755)
        target.write_bytes(value)
        target.chmod(0o644)
    if WWW.is_symlink():
        previous = WWW.resolve(strict=True)
        if previous.parent != RELEASES:
            raise ValueError('Existing static pointer is outside the managed releases')
    elif WWW.is_dir():
        previous = RELEASES / f'legacy-{stamp}'
    else:
        raise ValueError('Expected an existing /ios deployment')
    temporary = WWW.with_name('mobile-cloud-ios.next')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('A pending static deployment already exists')
    temporary.symlink_to(release, target_is_directory=True)
    if not WWW.is_symlink():
        WWW.rename(previous)
    try:
        temporary.replace(WWW)
        subprocess.run(['curl', '--max-time', '15', '--fail', '--silent', '--show-error',
                        'https://49.232.195.47/ios/model-contract.json'], check=True, capture_output=True, timeout=20)
    except Exception:
        if temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(previous, target_is_directory=True)
        temporary.replace(WWW)
        raise
    report = {'published_at': stamp, 'release': str(release), 'previous': str(previous),
              'archive_sha256': expected, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in content.items()}}
    evidence = SHARED / f'ios-responsive-{stamp}.json'
    evidence.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run with sudo')
    with LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        publish(args.archive, args.sha256)


if __name__ == '__main__':
    main()
