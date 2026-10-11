"""Root-only IP certificate operations; HTTP-01 temporarily uses port 80.

Only the first HTTP redirect block is patched, then restored byte for byte.
The existing 443 certificate and server block are never replaced.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

IP = '49.232.195.47'
SITE = Path('/etc/nginx/sites-available/mobile-cloud-backend')
REVIEW = Path('/etc/nginx/sites-available/campus-review')
STATE = Path('/var/lib/campus-review-acme')
WEBROOT = Path('/var/www/campus-review-acme')
CONFIG = Path('/etc/letsencrypt-campus-review')
LINEAGE = CONFIG / 'live/campus-review-ip'
TLS_CONFIG = Path('/etc/campus-review/tls.json')
CERTBOT = '/opt/campus-review-acme/bin/certbot'
DEPLOY_HOOK = '/usr/bin/python3 /usr/local/libexec/campus-review-acme.py deploy'
HTTP_BLOCK = f'''server {{
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name {IP};
    return 308 https://{IP}$request_uri;
}}
'''.encode()
CHALLENGE_BLOCK = f'''server {{
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name {IP};
    location ^~ /.well-known/acme-challenge/ {{
        root {WEBROOT};
        default_type text/plain;
        try_files $uri =404;
    }}
    location / {{ return 308 https://{IP}$request_uri; }}
}}
'''.encode()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reload_nginx():
    run('nginx', '-t')
    run('systemctl', 'reload', 'nginx')


def patched_http(original):
    if original.count(HTTP_BLOCK) != 1:
        raise ValueError('Port 80 block differs; refusing to edit shared Nginx configuration')
    return original.replace(HTTP_BLOCK, CHALLENGE_BLOCK, 1)


def restore_http(site=SITE, state=STATE):
    record = state / 'http-state.json'
    backup = state / 'http-original.conf'
    if not record.exists():
        return
    identity = json.loads(record.read_text())
    original = backup.read_bytes()
    if digest(original) != identity['original']:
        raise ValueError('HTTP backup hash differs')
    current_hash = digest(site.read_bytes())
    if current_hash not in (identity['original'], identity['patched']):
        raise ValueError('Shared Nginx configuration changed concurrently; preserved for operator review')
    if current_hash == identity['patched']:
        atomic_write(site, original, identity['mode'])
    # Also reload when the previous attempt restored the file but failed to reload.
    reload_nginx()
    record.unlink()
    backup.unlink()


@contextlib.contextmanager
def challenge_route(site=SITE, state=STATE):
    restore_http(site, state)
    original = site.read_bytes()
    patched = patched_http(original)
    mode = site.stat().st_mode & 0o777
    atomic_write(state / 'http-original.conf', original)
    atomic_write(state / 'http-state.json', json.dumps({
        'original': digest(original), 'patched': digest(patched), 'mode': mode,
    }).encode())
    try:
        atomic_write(site, patched, mode)
        reload_nginx()
        yield
    finally:
        restore_http(site, state)


def deploy():
    cert, key = LINEAGE / 'fullchain.pem', LINEAGE / 'privkey.pem'
    run('openssl', 'x509', '-in', str(cert), '-noout', '-checkip', IP)
    run('openssl', 'verify', '-purpose', 'sslserver', '-verify_ip', IP,
        '-untrusted', str(LINEAGE / 'chain.pem'), str(LINEAGE / 'cert.pem'))
    old = REVIEW.read_bytes()
    updated = re.sub(rb'(?m)^(\s*ssl_certificate\s+)[^;]+;',
                     lambda m: m[1] + str(cert).encode() + b';', old)
    updated = re.sub(rb'(?m)^(\s*ssl_certificate_key\s+)[^;]+;',
                     lambda m: m[1] + str(key).encode() + b';', updated)
    if len(re.findall(rb'(?m)^\s*ssl_certificate\s+', old)) != 1 or len(
            re.findall(rb'(?m)^\s*ssl_certificate_key\s+', old)) != 1:
        raise ValueError('Unexpected review TLS configuration')
    try:
        atomic_write(REVIEW, updated, 0o644)
        reload_nginx()  # nginx -t also checks certificate/private-key agreement.
    except Exception:
        atomic_write(REVIEW, old, 0o644)
        reload_nginx()
        raise
    TLS_CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    atomic_write(TLS_CONFIG, (json.dumps({'certificate': str(cert), 'key': str(key)},
                                       indent=2) + '\n').encode(), 0o644)


def certificate_command(operation):
    config = Path(str(CONFIG) + '-staging') if operation == 'issue-staging' else CONFIG
    args = [CERTBOT, '--config-dir', str(config), '--work-dir', str(STATE / 'work'),
            '--logs-dir', '/var/log/campus-review-acme', '--non-interactive']
    if operation in ('issue', 'issue-staging'):
        args += ['certonly', '--webroot', '--webroot-path', str(WEBROOT),
                 '--ip-address', IP, '--preferred-profile', 'shortlived',
                 '--cert-name', 'campus-review-ip', '--agree-tos',
                 '--register-unsafely-without-email']
        if operation == 'issue-staging':
            args += ['--staging']
    else:
        args += ['renew', '--cert-name', 'campus-review-ip', '--no-random-sleep-on-renew']
        if operation == 'dry-run':
            args += ['--dry-run']
        else:
            args += ['--deploy-hook', DEPLOY_HOOK]
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('issue-staging', 'issue', 'renew', 'dry-run', 'deploy', 'restore'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run as root')
    if args.operation == 'deploy':
        # Invoked inside certbot while the parent holds the issuance lock.
        deploy()
        return
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    WEBROOT.mkdir(parents=True, exist_ok=True, mode=0o755)
    WEBROOT.chmod(0o755)
    with (STATE / 'operation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.operation == 'restore':
            restore_http()
            return
        with challenge_route():
            run(*certificate_command(args.operation))
        if args.operation == 'issue':
            deploy()


if __name__ == '__main__':
    main()
