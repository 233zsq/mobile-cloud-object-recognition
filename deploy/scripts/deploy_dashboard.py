"""Stage a fixed release, then activate only the backend and dashboard routes.

The running CPU model, database, API credential, TLS and review site are retained.
Activation holds the same lock as the review site's ACME tool and rolls back on
failure. Run stage as gongyi, and activate through passwordless sudo.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request


BASE = Path('/home/gongyi/apps/mobile-cloud-backend')
SITE = Path('/etc/nginx/sites-available/mobile-cloud-backend')
CONFIG = Path('/home/gongyi/.config/mobile-cloud-backend/backend.env')
ACME_LOCK = Path('/var/lib/campus-review-acme/operation.lock')
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(arguments, **kwargs):
    return subprocess.run(arguments, check=True, timeout=180, **kwargs)


def managed_release(path):
    path = path.resolve(strict=True)
    if path.parent != BASE / 'releases':
        raise ValueError('Release is outside the managed directory')
    return path


def stage(args):
    import tarfile
    if os.geteuid() == 0:
        raise ValueError('Stage as the application owner, not root')
    archive = args.archive.resolve(strict=True)
    if archive.parent != BASE / 'shared' or digest(archive) != args.sha256:
        raise ValueError('Archive location or digest mismatch')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise ValueError('Expected a fixed Git commit')
    previous = managed_release(BASE / 'current')
    release = BASE / 'releases' / (args.revision[:7] + '-' + args.sha256[:8])
    if release.exists():
        raise ValueError('Release exists; use a new archive')
    release.mkdir(mode=0o755)
    with tarfile.open(archive) as source:
        source.extractall(release, filter='data')
    if (release / 'SOURCE_REVISION').read_text().strip() != args.revision:
        raise ValueError('Source revision mismatch')
    for lock in ('requirements.txt', 'requirements-dev.txt'):
        if (release / 'backend' / lock).read_bytes() != (previous / 'backend' / lock).read_bytes():
            raise ValueError('Runtime locks changed; provision a separate environment')
    environment = (previous / 'backend/.venv').resolve(strict=True)
    if not environment.is_relative_to(BASE / 'releases'):
        raise ValueError('Unexpected application environment')
    (release / 'backend/.venv').symlink_to(environment, target_is_directory=True)
    (release / '.env').symlink_to(CONFIG)
    (release / '.release.env').write_text('APP_VERSION=0.1.0+' + args.revision[:7] + '\n')
    output = BASE / 'shared' / ('dashboard-' + args.revision[:7])
    output.mkdir(mode=0o700)
    python = str(environment / 'bin/python')
    command([python, '-m', 'pip', 'check'], cwd=release / 'backend')
    command([python, '-B', str(release / 'deploy/scripts/verify_server.py'), 'tests',
             '--output', str(output / 'backend-tests.json')], cwd=release / 'backend')
    command([python, '-B', '-c', "from app import create_app; a=create_app(); c=a.test_client(); "
             "assert c.get('/').status_code==200; assert c.get('/assets/js/dashboard.js').status_code==200; "
             "assert c.get('/api/stats').status_code==401; assert c.get('/api/health').json['model_loaded']; "
             "print('Staged web, authentication and active model checks passed')"], cwd=release / 'backend')
    result = {'release': str(release), 'previous_release': str(previous), 'source_commit': args.revision,
              'nginx_sha256': digest(SITE), 'staging_tests_passed': True, 'evidence': str(output)}
    (output / 'staging.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


def pointer(release):
    temporary = BASE / ('current.dashboard-' + str(os.getpid()))
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('Pending release link exists')
    temporary.symlink_to(release, target_is_directory=True)
    temporary.replace(BASE / 'current')


def readiness(version):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            with opener.open('http://127.0.0.1:8080/api/health', timeout=3) as response:
                health = json.load(response)
            if health['model_loaded'] and health['model_version'] == version:
                with opener.open('http://127.0.0.1:8080/', timeout=3) as response:
                    if response.status == 200:
                        return health
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    raise RuntimeError('Backend or model readiness failed')


def activate(args):
    if os.geteuid() != 0:
        raise ValueError('Activation requires sudo')
    release = managed_release(args.release)
    previous = managed_release(BASE / 'current')
    if previous != args.expected_current.resolve(strict=True):
        raise ValueError('Current release changed since staging')
    if not ACME_LOCK.parent.is_dir():
        raise ValueError('Expected review ACME lock directory')
    with ACME_LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = SITE.read_bytes()
        if digest(SITE) != args.expected_nginx_sha256:
            raise ValueError('Nginx changed since staging')
        template = (release / 'deploy/nginx/mobile-cloud-backend.conf').read_bytes()
        begin = template.index(b'    location = / {')
        end = template.index(b'    location / { return 404; }', begin)
        additions = template[begin:end]
        if original != template.replace(additions, b'', 1):
            raise ValueError('Nginx differs from the approved baseline; refusing replacement')
        config_hash = digest(CONFIG)
        review_site = Path('/etc/nginx/sites-available/campus-review')
        review_hash = digest(review_site)
        inference_unit = Path('/etc/systemd/system/mobile-cloud-inference.service')
        inference_hash = digest(inference_unit)
        settings = dict(line.split('=', 1) for line in CONFIG.read_text().splitlines() if line and not line.startswith('#'))
        version = settings['INFERENCE_MODEL_VERSION']
        backup = BASE / 'shared' / ('dashboard-rollback-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        backup.mkdir(mode=0o700)
        (backup / 'nginx.conf').write_bytes(original)
        (backup / 'previous-release.txt').write_text(str(previous) + '\n')
        try:
            SITE.write_bytes(template)
            command(['nginx', '-t'])
            pointer(release)
            command(['systemctl', 'restart', 'mobile-cloud-backend'])
            health = readiness(version)
            command(['systemctl', 'reload', 'nginx'])
            assert digest(CONFIG) == config_hash
            assert digest(review_site) == review_hash
            assert digest(inference_unit) == inference_hash
            command(['systemctl', 'is-active', '--quiet', 'mobile-cloud-inference', 'campus-review'])
        except BaseException:
            SITE.write_bytes(original)
            pointer(previous)
            command(['nginx', '-t'])
            command(['systemctl', 'restart', 'mobile-cloud-backend'])
            command(['systemctl', 'reload', 'nginx'])
            print(json.dumps({'activated': False, 'rolled_back_to': str(previous)}), flush=True)
            raise
        result = {'activated': True, 'release': str(release), 'previous_release': str(previous),
                  'health': health, 'rollback': str(backup), 'database_migration': False,
                  'credentials_unchanged': True, 'review_site_unchanged': True, 'inference_unit_unchanged': True}
        evidence = BASE / 'shared' / ('dashboard-' + (release / 'SOURCE_REVISION').read_text().strip()[:7]) / 'activation.json'
        evidence.write_text(json.dumps(result, indent=2) + '\n')
        os.chown(evidence, release.stat().st_uid, release.stat().st_gid)
        print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser()
    phases = parser.add_subparsers(dest='phase', required=True)
    staging = phases.add_parser('stage')
    staging.add_argument('--archive', type=Path, required=True)
    staging.add_argument('--sha256', required=True)
    staging.add_argument('--revision', required=True)
    activating = phases.add_parser('activate')
    activating.add_argument('--release', type=Path, required=True)
    activating.add_argument('--expected-current', type=Path, required=True)
    activating.add_argument('--expected-nginx-sha256', required=True)
    args = parser.parse_args()
    globals()[args.phase](args)


if __name__ == '__main__':
    main()
