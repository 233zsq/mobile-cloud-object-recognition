"""Run as ubuntu in an extracted release. Owns only campus-review resources."""
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[2]
home = Path.home()
app = home / 'apps/campus-review'
shared = app / 'shared'
venv = app / 'venv'
config = home / '.config/campus-review/review.env'
current = app / 'current'
site = Path('/etc/nginx/sites-available/campus-review')
old_site = Path('/etc/nginx/sites-enabled/mobile-cloud-backend')
old_digest = hashlib.sha256(old_site.read_bytes()).hexdigest()
source = json.loads((root / 'SOURCE.json').read_text())
for filename, expected in source['files'].items():
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError('Release source hash differs: ' + filename)
if os.getuid()!=1000 or home.name!='ubuntu':
    raise ValueError('Deploy as the authorized ubuntu account')


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def install(value, target):
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as temp:
        temp.write(value)
        name = temp.name
    try:
        run('sudo', '-n', 'install', '-o', 'root', '-g', 'root', '-m', '0644', name, str(target))
    finally:
        Path(name).unlink()


if not site.exists():
    for port in (8081, 8443):
        with socket.socket() as check:
            check.bind(('0.0.0.0', port))
shared.mkdir(parents=True, exist_ok=True, mode=0o700)
config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
if not config.exists():
    config.write_text('REVIEW_SECRET_KEY=' + secrets.token_urlsafe(48) + '\nREVIEW_DATA_DIR=' + str(shared) + '\n')
    config.chmod(0o600)
if not venv.exists():
    run(sys.executable, '-m', 'venv', str(venv))
python = venv / 'bin/python'
run(str(python), '-m', 'pip', 'install', '--only-binary=:all:', '-r', str(root / 'review/requirements-dev.txt'))
run(str(python), '-m', 'pytest', '-q', str(root / 'review/tests'), '--basetemp=' + str(root / 'test-temp'))
install(f'''# Managed by campus-review; never binds 443.
server {{
    listen 8443 ssl;
    listen [::]:8443 ssl;
    server_name 49.232.195.47;
    ssl_certificate /etc/mobile-cloud-backend/tls/server.crt;
    ssl_certificate_key /etc/mobile-cloud-backend/tls/server.key;
    client_max_body_size 9m;
    access_log off;
    location / {{
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 90s;
    }}
}}
''', site)
enabled = Path('/etc/nginx/sites-enabled/campus-review')
if not enabled.exists():
    run('sudo', '-n', 'ln', '-s', str(site), str(enabled))
run('sudo', '-n', 'nginx', '-t')
install(f'''[Unit]
Description=Campus collaborative photo review
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory={current}/review
EnvironmentFile={config}
ExecStart={venv}/bin/gunicorn --bind 127.0.0.1:8081 --workers 1 --threads 2 --timeout 90 --access-logfile /dev/null wsgi:app
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={shared}
MemoryHigh=192M
MemoryMax=256M

[Install]
WantedBy=multi-user.target
''', Path('/etc/systemd/system/campus-review.service'))
previous = current.resolve() if current.exists() else None
pending = app / 'current.new'
pending.unlink(missing_ok=True)
pending.symlink_to(root)
pending.replace(current)
try:
    run('sudo', '-n', 'systemctl', 'daemon-reload')
    run('sudo', '-n', 'systemctl', 'enable', '--now', 'campus-review')
    run('sudo', '-n', 'systemctl', 'restart', 'campus-review')
    import time
    for attempt in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2) as response:
                assert json.load(response)['service']=='campus-review'
            break
        except (OSError, AssertionError):
            if attempt==19:
                raise
            time.sleep(.5)
    run('sudo', '-n', 'systemctl', 'reload', 'nginx')
    if hashlib.sha256(old_site.read_bytes()).hexdigest()!=old_digest:
        raise ValueError('Existing backend configuration changed')
    with urllib.request.urlopen('http://127.0.0.1:8080/api/health') as response:
        assert json.load(response)['status']=='ok'
except Exception:
    if previous:
        pending.symlink_to(previous); pending.replace(current)
        run('sudo', '-n', 'systemctl', 'restart', 'campus-review')
    else:
        run('sudo', '-n', 'systemctl', 'stop', 'campus-review')
    raise

environment = os.environ.copy()
for line in config.read_text().splitlines():
    key, value = line.split('=', 1)
    environment[key] = value
setup_file = shared / 'admin-setup.txt'
if not setup_file.exists():
    result = subprocess.run([str(python), '-m', 'flask', '--app', 'campus_review:create_app', 'bootstrap'],
                            cwd=root / 'review', env=environment, capture_output=True, text=True)
    if result.returncode==0:
        setup_file.write_text('https://49.232.195.47:8443' + result.stdout.strip() + '\n')
        setup_file.chmod(0o600)
print(json.dumps({'service': 'campus-review', 'url': 'https://49.232.195.47:8443',
                  'release': str(root), 'git_commit': source['git_commit'],
                  'working_tree_dirty': source['working_tree_dirty'], 'existing_backend_config_sha256': old_digest,
                  'admin_setup_file': str(setup_file)}, indent=2))
