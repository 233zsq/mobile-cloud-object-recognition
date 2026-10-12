"""Opt the existing 443 service into the already-issued, automatically renewed IP certificate.

Does not issue certificates, alter ports, credentials, API routes or the 8443 site.
The existing ACME deploy hook reloads nginx after renewal, refreshing both listeners.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import time


SITE = Path('/etc/nginx/sites-available/mobile-cloud-backend')
LINEAGE = Path('/etc/letsencrypt-campus-review/live/campus-review-ip')
LOCK = Path('/var/lib/campus-review-acme/operation.lock')
BACKUPS = Path('/home/gongyi/apps/mobile-cloud-backend/shared')


def trusted_config(text):
    paths = {
        'ssl_certificate': ('/etc/mobile-cloud-backend/tls/server.crt', str(LINEAGE / 'fullchain.pem')),
        'ssl_certificate_key': ('/etc/mobile-cloud-backend/tls/server.key', str(LINEAGE / 'privkey.pem')),
    }
    for directive, (legacy, target) in paths.items():
        pattern = re.compile(r'(?m)^(\s*' + directive + r'\s+)([^;\n]+);')
        matches = list(pattern.finditer(text))
        if len(matches) != 1 or matches[0][2] not in (legacy, target):
            raise ValueError(f'Unexpected {directive}; refusing to overwrite an unrelated TLS configuration')
        text = pattern.sub(lambda match: match[1] + target + ';', text)
    return text


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)


def readiness():
    # systemctl reload returns before the old nginx workers have finished draining.
    for attempt in range(8):
        try:
            run('curl', '--max-time', '3', '--fail', '--silent', '--show-error', 'https://49.232.195.47/api/health')
            return
        except subprocess.CalledProcessError as error:
            if attempt == 7:
                raise RuntimeError(f'Public TLS readiness failed: {error.stderr.strip()}') from error
            time.sleep(0.3)


def activate(dry_run=False):
    original = SITE.read_text(encoding='utf-8')
    updated = trusted_config(original)
    if dry_run:
        print('443 will reuse the existing trusted IP lineage; 8443, port 80 and API routes are unchanged.')
        return
    run('openssl', 'x509', '-in', str(LINEAGE / 'cert.pem'), '-noout', '-checkip', '49.232.195.47', '-checkend', '86400')
    run('openssl', 'verify', '-purpose', 'sslserver', '-verify_ip', '49.232.195.47',
        '-untrusted', str(LINEAGE / 'chain.pem'), str(LINEAGE / 'cert.pem'))
    if updated == original:
        print('443 already uses the trusted lineage.')
        return
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = BACKUPS / f'nginx-pre-public-tls-{stamp}.conf'
    shutil.copy2(SITE, backup)
    SITE.write_text(updated, encoding='utf-8')
    try:
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        readiness()
    except Exception:
        shutil.copy2(backup, SITE)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        raise
    print(f'Trusted TLS active. Backup: {backup}; config SHA-256: {hashlib.sha256(SITE.read_bytes()).hexdigest()}')


def main():
    import fcntl
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run with sudo')
    with LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        activate(args.dry_run)


if __name__ == '__main__':
    main()
