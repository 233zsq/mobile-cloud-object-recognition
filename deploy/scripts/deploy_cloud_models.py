"""Activate a fixed public source bundle and two existing approved CPU packages.

Run with sudo. Preserves API credentials, TLS, ports, database schema and /ios.
Backs up config/unit/current pointer and restores all three if readiness fails.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shlex
import subprocess
import tarfile
import time

BASE = Path('/home/gongyi/apps/mobile-cloud-backend')
CONFIG = Path('/home/gongyi/.config/mobile-cloud-backend/backend.env')
UNIT = Path('/etc/systemd/system/mobile-cloud-inference.service')
REGISTRY = BASE / 'shared/inference-models.json'
LOCK = Path('/var/lib/campus-review-acme/operation.lock')


def run(arguments, cwd=None):
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Deployment check failed: ' + Path(arguments[0]).name + '; output withheld to protect configuration')
    return result.stdout.strip()


def atomic(path, content, mode=0o600):
    original = path.stat() if path.exists() else None
    temporary = path.with_name(path.name + '.cloud-models.tmp')
    with temporary.open('xb') as stream:
        os.fchmod(stream.fileno(), original.st_mode & 0o777 if original else mode)
        if original:
            os.fchown(stream.fileno(), original.st_uid, original.st_gid)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def source_files(archive, digest):
    if archive.stat().st_size > 16 * 1024 * 1024 or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError('Source bundle size or hash differs')
    with tarfile.open(archive) as source:
        files = {}
        total = 0
        for member in source:
            path = PurePosixPath(member.name)
            if (not path.parts or not member.isfile() or path.is_absolute() or '..' in path.parts
                    or str(path) != member.name or member.name in files
                    or (path.parts[0] not in ('backend', 'web', 'database', 'deploy') and member.name != 'SOURCE_REVISION')
                    or any(part.startswith('.') for part in path.parts) or member.size > 4 * 1024 * 1024):
                raise ValueError('Unexpected source bundle member')
            total += member.size
            if total > 32 * 1024 * 1024:
                raise ValueError('Expanded source bundle exceeds limit')
            files[member.name] = source.extractfile(member).read()
    return files


def pointer(release):
    temporary = BASE / 'current.cloud-models-next'
    temporary.symlink_to(release, target_is_directory=True)
    temporary.replace(BASE / 'current')


def registry_for(packages, cpu_python):
    names = {'campus-evolve-v2': ('进阶版 v2', '当前推荐版本，加入审核后的补充照片。'),
             'campus-gpu-v1': ('基准版 v1', '最初 GPU 模型，采用较早的类别口径，供对比使用。')}
    models = []
    for package in packages:
        package = package.resolve(strict=True)
        if package.parent != BASE / 'models':
            raise ValueError('Expected an existing managed model package')
        verified = json.loads(run([str(cpu_python), '-B', str(package / 'verify_package.py')]))
        meta = json.loads((package / 'release/metadata.json').read_text())
        version = meta['model_version']
        if version not in names or verified['model_sha256'] != meta['sha256'] or not verified['passed']:
            raise ValueError('Only approved baseline v1 and evolve v2 are supported')
        models.append({'model_version': version, 'model_sha256': meta['sha256'], 'category_version': meta['category_version'],
            'labels_sha256': meta['labels_sha256'], 'labels': [item['label_key'] for item in meta['categories']],
            'low_confidence_threshold': meta['low_confidence_threshold'], 'status': meta['status'],
            'display_name': names[version][0], 'description': names[version][1], 'package': str(package)})
    if {m['model_version'] for m in models} != set(names) or len(models) != 2:
        raise ValueError('Exactly two distinct approved packages are required')
    return {'schema_version': 1, 'default_model_version': 'campus-evolve-v2', 'models': models}


def activate(args):
    if not re.fullmatch('[0-9a-f]{40}', args.revision):
        raise ValueError('Expected a fixed Git commit')
    archive = args.archive.resolve(strict=True)
    if archive.parent != BASE / 'shared':
        raise ValueError('Upload the source bundle to the managed shared directory')
    files = source_files(archive, args.sha256)
    if files.get('SOURCE_REVISION', b'').decode().strip() != args.revision:
        raise ValueError('Source commit differs')
    previous = (BASE / 'current').resolve(strict=True)
    if previous.parent != BASE / 'releases':
        raise ValueError('Unexpected current source directory')
    old_unit, old_env = UNIT.read_bytes(), CONFIG.read_bytes()
    old_registry = REGISTRY.read_bytes() if REGISTRY.exists() else None
    old_command = shlex.split(next(line[10:] for line in old_unit.decode().splitlines() if line.startswith('ExecStart=')))
    cpu_python = Path(old_command[0])
    if not cpu_python.is_file() or not cpu_python.is_relative_to(BASE / 'models'):
        raise ValueError('Expected the existing CPU environment')
    registry = registry_for(args.package, cpu_python)
    env_values = dict(line.split('=', 1) for line in old_env.decode().splitlines() if line and not line.startswith('#'))
    default = next(model for model in registry['models'] if model['model_version'] == registry['default_model_version'])
    if (env_values.get('INFERENCE_MODEL_VERSION'), env_values.get('INFERENCE_MODEL_SHA256')) != (default['model_version'], default['model_sha256']):
        raise ValueError('Keep the existing default model pinned; activate it separately first')
    release = BASE / 'releases' / (args.revision[:12] + '-cloud-models')
    release.mkdir(mode=0o755)
    for name, data in files.items():
        path = release / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name in ('requirements.txt', 'requirements-dev.txt'):
        if (release / 'backend' / name).read_bytes() != (previous / 'backend' / name).read_bytes():
            raise ValueError('Backend dependency locks differ')
    (release / 'backend/.venv').symlink_to((previous / 'backend/.venv').resolve(strict=True), target_is_directory=True)
    (release / '.env').symlink_to(CONFIG)
    (release / '.release.env').write_text('APP_VERSION=0.1.0+' + args.revision[:7] + '\n')
    python = release / 'backend/.venv/bin/python'
    backend = release / 'backend'
    run([str(python), '-m', 'pytest', 'tests/test_infer.py', 'tests/test_cloud_models.py', '-q'], cwd=backend)
    run([str(cpu_python), 'test_server.py'], cwd=backend / 'inference_service')
    for model in registry['models']:
        package = Path(model['package'])
        run([str(python), '-m', 'flask', '--app', 'app:create_app', 'db-seed', '--categories', str(package / 'categories.json')], cwd=backend)
        run([str(python), '-m', 'flask', '--app', 'app:create_app', 'register-model', '--metadata', str(package / 'release/metadata.json')], cwd=backend)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = BASE / 'shared/model-rollbacks' / (stamp + '-multi-model')
    backup.mkdir(parents=True, mode=0o700)
    (backup / 'backend.env').write_bytes(old_env)
    (backup / 'inference.service').write_bytes(old_unit)
    (backup / 'previous-release.txt').write_text(str(previous) + '\n')
    if old_registry is not None:
        (backup / 'registry.json').write_bytes(old_registry)
    env_lines = [line for line in old_env.decode().splitlines(keepends=True) if not line.startswith('INFERENCE_REGISTRY=')]
    new_env = (''.join(env_lines).rstrip('\n') + '\nINFERENCE_REGISTRY=' + str(REGISTRY) + '\n').encode()
    if '--registry' in old_command:
        index = old_command.index('--registry')
        del old_command[index:index+2]
    new_unit = re.sub(r'^ExecStart=.*$', lambda _: 'ExecStart=' + shlex.join(old_command + ['--registry', str(REGISTRY)]), old_unit.decode(), flags=re.MULTILINE)
    try:
        atomic(REGISTRY, (json.dumps(registry, ensure_ascii=False, indent=2) + '\n').encode(), 0o640)
        os.chown(REGISTRY, 0, pwd.getpwnam('gongyi').pw_gid)
        atomic(CONFIG, new_env)
        atomic(UNIT, new_unit.encode(), 0o644)
        run(['systemd-analyze', 'verify', str(UNIT)])
        pointer(release)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'restart', 'mobile-cloud-inference'])
        probe = "from app import create_app; a=create_app(); assert all(c.health()['model_loaded'] for c in a.extensions['inference_clients'].values()); print('ready')"
        for attempt in range(40):
            try:
                run([str(python), '-B', '-c', probe], cwd=backend)
                break
            except RuntimeError:
                if attempt == 39:
                    raise
                time.sleep(.5)
        run(['systemctl', 'restart', 'mobile-cloud-backend'])
        probe = ("import json, urllib.request; from app import create_app; a=create_app(); "
            "r=urllib.request.Request('https://49.232.195.47/api/models',headers={'Authorization':'Bearer '+a.config['API_TOKEN']}); "
            "d=json.load(urllib.request.urlopen(r,timeout=5)); assert len(d['models'])==2 and all(m['available'] for m in d['models']); "
            "assert {m['model_version'] for m in d['models']}=={'campus-gpu-v1','campus-evolve-v2'}; print(json.dumps(d,ensure_ascii=False))")
        for attempt in range(30):
            try:
                public = json.loads(run([str(python), '-B', '-c', probe], cwd=backend))
                break
            except (RuntimeError, ValueError):
                if attempt == 29:
                    raise
                time.sleep(.5)
    except Exception:
        pointer(previous)
        atomic(CONFIG, old_env)
        atomic(UNIT, old_unit)
        if old_registry is not None:
            atomic(REGISTRY, old_registry)
        else:
            REGISTRY.unlink(missing_ok=True)
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'restart', 'mobile-cloud-inference', 'mobile-cloud-backend'])
        raise RuntimeError('Activation failed; restored previous source, configuration and worker') from None
    report = {'source_commit': args.revision, 'release': str(release), 'previous_release': str(previous),
        'rollback_directory': str(backup), 'models': public, 'credentials_preserved': True,
        'tls_ports_and_static_ios_changed': False, 'database_schema_changed': False}
    atomic(BASE / 'shared/cloud-models-activation.json', (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--package', required=True, action='append', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run with sudo')
    with LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        activate(args)


if __name__ == '__main__':
    main()
