"""Provision this application's release with existing passwordless sudo.

Run as gongyi from an extracted release. Credentials are generated only on the
server and never printed. Existing project checkouts are left in place.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BASE = Path('/home/gongyi/apps/mobile-cloud-backend')
CONFIG = Path('/home/gongyi/.config/mobile-cloud-backend/backend.env')
SECRET_VALUES = []


def command(args, input=None, show=False):
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=180)
    if result.returncode or show:
        message = result.stdout + result.stderr
        for value in SECRET_VALUES:
            message = message.replace(value, '[REDACTED]')
        print(message, end='', flush=True)
    result.check_returncode()
    return result.stdout.strip()


def install(source, destination, mode='0644'):
    command(['sudo', '-n', 'install', '-D', '-o', 'root', '-g', 'root', '-m', mode,
             str(source), str(destination)])


def sql(query):
    return command(['sudo', '-n', 'mysql', '--protocol=socket', '--batch', '--skip-column-names'], input=query)


def settings():
    if not CONFIG.exists():
        existing = sql("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='object_recognition';")
        if existing:
            raise RuntimeError('Existing application database without managed credentials; refusing to claim it.')
        CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        CONFIG.parent.chmod(0o700)
        data = {
            'APP_VERSION': '0.1.0+' + (ROOT / 'SOURCE_REVISION').read_text().strip()[:7],
            'APP_DEBUG': 'false', 'LOG_LEVEL': 'INFO', 'SERVER_HOST': '127.0.0.1',
            'SERVER_PORT': '8080', 'MAX_CONTENT_LENGTH': '10485760',
            'DB_HOST': '127.0.0.1', 'DB_PORT': '3306', 'DB_NAME': 'object_recognition',
            'DB_USER': 'object_recognition', 'DB_PASSWORD': secrets.token_hex(24),
            'API_TOKEN': secrets.token_hex(32), 'API_BASE_URL': 'https://49.232.195.47', 'MODEL_DIR': '',
        }
        descriptor = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(''.join(f'{key}={value}\n' for key, value in data.items()))
    else:
        data = dict(line.split('=', 1) for line in CONFIG.read_text().splitlines() if line and not line.startswith('#'))
    if data['DB_NAME'] != 'object_recognition' or data['DB_USER'] != 'object_recognition':
        raise RuntimeError('Unexpected database configuration.')
    for key in ('DB_PASSWORD', 'API_TOKEN'):
        if len(data[key]) < 32 or any(character not in '0123456789abcdef' for character in data[key]):
            raise RuntimeError('Unexpected credential format.')
        SECRET_VALUES.append(data[key])
    CONFIG.chmod(0o600)
    dotenv = ROOT / '.env'
    if dotenv.is_symlink():
        if dotenv.resolve() != CONFIG.resolve():
            raise RuntimeError('Unexpected release configuration link.')
    elif dotenv.exists():
        raise RuntimeError('Unexpected release configuration file.')
    else:
        dotenv.symlink_to(CONFIG)
    return data


def application():
    data = settings()
    account = "'object_recognition'@'127.0.0.1'"
    sql(f"CREATE DATABASE IF NOT EXISTS object_recognition CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;\n"
        f"CREATE USER IF NOT EXISTS {account} IDENTIFIED BY '{data['DB_PASSWORD']}';\n"
        f"GRANT ALL PRIVILEGES ON object_recognition.* TO {account};\n")
    python = ROOT / 'backend/.venv/bin/python'
    try:
        for arguments in [('db-init',), ('db-seed',), ('register-model', '--metadata', str(ROOT / 'database/seeds/expanded-cpu-v1.metadata.json'))]:
            command([str(python), '-m', 'flask', '--app', 'app:create_app', *arguments], show=True)
    finally:
        sql(f"REVOKE ALL PRIVILEGES ON object_recognition.* FROM {account};\n"
            f"GRANT SELECT, INSERT, UPDATE ON object_recognition.* TO {account};\n")
    revision = (ROOT / 'SOURCE_REVISION').read_text().strip()
    (ROOT / '.release.env').write_text('APP_VERSION=0.1.0+' + revision[:7] + '\n')
    current = BASE / 'current'
    if current.exists() and not current.is_symlink():
        raise RuntimeError('Current release path must be a symbolic link.')
    candidate = BASE / 'current.next'
    if candidate.exists() or candidate.is_symlink():
        raise RuntimeError('Unexpected pending release link.')
    candidate.symlink_to(ROOT, target_is_directory=True)
    candidate.replace(current)
    install(ROOT / 'deploy/systemd/mobile-cloud-backend.service', '/etc/systemd/system/mobile-cloud-backend.service')
    command(['sudo', '-n', 'systemd-analyze', 'verify', '/etc/systemd/system/mobile-cloud-backend.service'], show=True)
    command(['sudo', '-n', 'systemctl', 'daemon-reload'])
    command(['sudo', '-n', 'systemctl', 'enable', '--now', 'mysql', 'mobile-cloud-backend'], show=True)
    command(['sudo', '-n', 'systemctl', 'restart', 'mobile-cloud-backend'])
    print(json.dumps({'phase': 'application', 'release': str(ROOT), 'config': str(CONFIG)}))


def nginx():
    data = settings()
    tls = '/etc/mobile-cloud-backend/tls'
    command(['sudo', '-n', 'install', '-d', '-m', '0700', tls])
    exists = subprocess.run(['sudo', '-n', 'test', '-f', tls + '/server.crt']).returncode == 0
    if not exists:
        command(['sudo', '-n', 'openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-sha256',
                 '-nodes', '-days', '90', '-keyout', tls + '/server.key', '-out', tls + '/server.crt',
                 '-subj', '/CN=49.232.195.47', '-addext', 'subjectAltName=IP:49.232.195.47,IP:127.0.0.1',
                 '-addext', 'extendedKeyUsage=serverAuth'])
        command(['sudo', '-n', 'chmod', '0600', tls + '/server.key', tls + '/server.crt'])
    public = BASE / 'shared/server.crt'
    public.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    public.write_text(command(['sudo', '-n', 'cat', tls + '/server.crt']) + '\n')
    public.chmod(0o644)
    rendered = BASE / 'shared/auth-map.conf'
    descriptor = os.open(rendered, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write((ROOT / 'deploy/nginx/auth-map.conf.example').read_text().replace('__API_TOKEN__', data['API_TOKEN']))
    try:
        install(rendered, '/etc/nginx/conf.d/mobile-cloud-auth.conf', '0600')
    finally:
        rendered.unlink()
    install(ROOT / 'deploy/nginx/mobile-cloud-backend.conf', '/etc/nginx/sites-available/mobile-cloud-backend')
    default = Path('/etc/nginx/sites-enabled/default')
    if default.is_symlink() and default.resolve() == Path('/etc/nginx/sites-available/default'):
        command(['sudo', '-n', 'unlink', str(default)])
    enabled = Path('/etc/nginx/sites-enabled/mobile-cloud-backend')
    if not enabled.exists():
        command(['sudo', '-n', 'ln', '-s', '/etc/nginx/sites-available/mobile-cloud-backend', str(enabled)])
    command(['sudo', '-n', 'nginx', '-t'], show=True)
    command(['sudo', '-n', 'systemctl', 'enable', '--now', 'nginx'], show=True)
    command(['sudo', '-n', 'systemctl', 'reload', 'nginx'])
    print(json.dumps({'phase': 'nginx', 'certificate': str(public), 'api': 'https://49.232.195.47'}))


def backup():
    install(ROOT / 'deploy/scripts/backup_database.py', '/usr/local/lib/mobile-cloud-backend/backup_database.py')
    for name in ('mobile-cloud-backend-backup.service', 'mobile-cloud-backend-backup.timer'):
        install(ROOT / 'deploy/systemd' / name, '/etc/systemd/system/' + name)
    command(['sudo', '-n', 'systemctl', 'daemon-reload'])
    command(['sudo', '-n', 'systemctl', 'enable', '--now', 'mobile-cloud-backend-backup.timer'], show=True)
    command(['sudo', '-n', 'python3', '-B', '/usr/local/lib/mobile-cloud-backend/backup_database.py'], show=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['mysql-config', 'application', 'nginx', 'backup'])
    args = parser.parse_args()
    if ROOT.parent != BASE / 'releases':
        raise RuntimeError('Run this script only from the managed releases directory.')
    if args.phase == 'mysql-config':
        install(ROOT / 'deploy/mysql/mobile-cloud-backend.cnf', '/etc/mysql/mysql.conf.d/zz-mobile-cloud-backend.cnf')
    else:
        os.chdir(ROOT / 'backend')
        globals()[args.phase]()


if __name__ == '__main__':
    main()
