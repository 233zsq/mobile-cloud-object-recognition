"""Activate an approved CPU package on the existing host, with config rollback."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.request

BASE = Path('/home/gongyi/apps/mobile-cloud-backend')
CONFIG = Path('/home/gongyi/.config/mobile-cloud-backend/backend.env')
UNIT = Path('/etc/systemd/system/mobile-cloud-inference.service')


def run(args, *, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Command failed: ' + Path(args[0]).name + ' (exit ' + str(result.returncode) + '; output withheld to protect deployment credentials)')
    return result.stdout.strip()


def atomic(path, content, mode=0o600):
    temp = path.with_name(path.name + '.model-update.tmp')
    with temp.open('xb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:8080/api/health', timeout=5) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--model-sha256', required=True)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    if package.parent != (BASE / 'models').resolve() or not re.fullmatch('[0-9a-f]{64}', args.model_sha256):
        raise ValueError('Expected managed package directory and explicit model SHA-256')
    meta = json.loads((package / 'release/metadata.json').read_text())
    if meta['sha256'] != args.model_sha256 or meta['status'] != 'frozen':
        raise ValueError('Selected model identity or status differs')
    old_unit = run(['sudo', '-n', 'cat', str(UNIT)])
    old_env = CONFIG.read_bytes()
    env = dict(line.split('=', 1) for line in old_env.decode().splitlines() if line and not line.startswith('#'))
    old_model = env['INFERENCE_MODEL_VERSION']
    if old_model == meta['model_version']:
        raise ValueError('This model is already configured; inspect health instead of reactivating')
    command_line = next(line[10:] for line in old_unit.splitlines() if line.startswith('ExecStart='))
    cpu_python = Path(shlex.split(command_line)[0])
    old_package = cpu_python.parents[2]
    if old_package.parent != BASE / 'models' or not cpu_python.is_file():
        raise ValueError('Existing managed CPU interpreter is unavailable')
    if (old_package/'locks/linux-py312-runtime.lock').read_bytes() != (package/'locks/linux-py312-runtime.lock').read_bytes():
        raise ValueError('Runtime dependency lock differs; provision a separate environment first')
    integrity = json.loads(run([str(cpu_python), '-B', str(package/'verify_package.py')]))
    if integrity['model_sha256'] != args.model_sha256:
        raise ValueError('Deployment package verification failed')
    source = (BASE/'current').resolve(strict=True)
    backend = source/'backend'
    python = backend/'.venv/bin/python'
    # Registration is additive and refuses changes to an existing version.
    run([str(python), '-m', 'flask', '--app', 'app:create_app', 'db-seed', '--categories', str(package/'categories.json')], cwd=backend)
    run([str(python), '-m', 'flask', '--app', 'app:create_app', 'register-model', '--metadata', str(package/'release/metadata.json')], cwd=backend)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = BASE/'shared/model-rollbacks'/f'{stamp}-{meta["model_version"]}'
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    (backup/'backend.env').write_bytes(old_env); (backup/'backend.env').chmod(0o600)
    (backup/'inference.service').write_text(old_unit+'\n'); (backup/'inference.service').chmod(0o600)
    new_command = shlex.join([str(cpu_python), str(BASE/'current/backend/inference_service/server.py'),
                             '--package', str(package), '--socket', '/run/mobile-cloud-inference/model.sock',
                             '--model-version', meta['model_version'], '--model-sha256', meta['sha256']])
    new_unit = re.sub(r'^WorkingDirectory=.*$', 'WorkingDirectory='+str(package), old_unit, flags=re.MULTILINE)
    new_unit = re.sub(r'^ExecStart=.*$', 'ExecStart='+new_command, new_unit, flags=re.MULTILINE)
    unit_temp = backup/'new-inference.service'
    unit_temp.write_text(new_unit+'\n')
    # Keep every credential and all unrelated environment values byte-identical.
    replacements = {'INFERENCE_MODEL_VERSION': meta['model_version'], 'INFERENCE_MODEL_SHA256': meta['sha256']}
    lines = old_env.decode().splitlines(keepends=True)
    for key, value in replacements.items():
        assert sum(line.startswith(key+'=') for line in lines) == 1
        lines = [key+'='+value+'\n' if line.startswith(key+'=') else line for line in lines]
    new_env = ''.join(lines).encode()
    try:
        run(['sudo','-n','install','-o','root','-g','root','-m','0644',str(unit_temp),str(UNIT)])
        run(['sudo','-n','systemd-analyze','verify',str(UNIT)])
        atomic(CONFIG,new_env)
        run(['sudo','-n','systemctl','daemon-reload'])
        run(['sudo','-n','systemctl','restart','mobile-cloud-inference'])
        probe = "from app import create_app; import json; a=create_app(); print(json.dumps(a.extensions['inference_client'].health()))"
        for _ in range(40):
            try:
                worker = json.loads(run([str(python),'-B','-c',probe],cwd=backend))
                if worker['model_version'] == meta['model_version'] and worker['model_sha256'] == meta['sha256']:
                    break
            except (RuntimeError, ValueError, KeyError):
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('New worker did not become ready')
        run(['sudo','-n','systemctl','restart','mobile-cloud-backend'])
        for _ in range(30):
            try:
                result=health()
                if result.get('model_loaded') and result.get('model_version')==meta['model_version']:
                    break
            except Exception:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('Backend did not expose the selected model')
    except Exception:
        atomic(CONFIG,old_env)
        run(['sudo','-n','install','-o','root','-g','root','-m','0644',str(backup/'inference.service'),str(UNIT)])
        run(['sudo','-n','systemctl','daemon-reload'])
        run(['sudo','-n','systemctl','restart','mobile-cloud-inference','mobile-cloud-backend'])
        raise RuntimeError('Activation failed; restored previous configuration and restarted both services') from None
    receipt={'model_version':meta['model_version'],'model_sha256':meta['sha256'],'previous_model':old_model,
             'rollback_directory':str(backup),'backend_source':str(source),'health':result,
             'credentials_preserved':True,'nginx_tls_and_ports_changed':False,'package_integrity':integrity}
    output=BASE/'shared'/f'{meta["model_version"]}-activation.json'
    atomic(output,(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    print(json.dumps(receipt,ensure_ascii=False))


if __name__ == '__main__':
    main()
