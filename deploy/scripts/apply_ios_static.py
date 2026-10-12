"""Add or refresh the iPhone web client (/ios) nginx static locations.

The page is plain static files, so no Flask release, database regression or model
switch is involved: only the two/three locations below are added to the 443
server block, right before the catch-all 404. Re-running the script replaces a
previously inserted block instead of duplicating it, so config edits stay
reviewable. It holds the same ACME operation lock as the review site, validates
with nginx -t before reloading, and restores the previous configuration when
validation or reload fails.

Run the apply step through passwordless sudo:

    sudo -n python3 deploy/scripts/apply_ios_static.py
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess


SITE = Path('/etc/nginx/sites-available/mobile-cloud-backend')
BASE = Path('/home/gongyi/apps/mobile-cloud-backend')
ACME_LOCK = Path('/var/lib/campus-review-acme/operation.lock')
WWW = Path('/var/www/mobile-cloud-ios')
START = '    # iPhone 网页版：静态页由 nginx 直接托管，见仓库 web/ios/README.md'
ANCHOR = '    location / { return 404; }'

BLOCK = '''    # iPhone 网页版：静态页由 nginx 直接托管，见仓库 web/ios/README.md
    location = /ios {{
        return 308 /ios/;
    }}

    location /ios/ {{
        alias {root}/;
        index index.html;
        add_header Cache-Control "no-cache";
        add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; manifest-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";
        add_header X-Content-Type-Options "nosniff";
        add_header Referrer-Policy "no-referrer";
    }}

    # webmanifest 不在 nginx 内置 mime.types 中；用精确匹配单独声明，避免覆盖全局 types
    location = /ios/manifest.webmanifest {{
        alias {root}/manifest.webmanifest;
        default_type application/manifest+json;
        add_header Cache-Control "no-cache";
    }}

'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"命令失败：{' '.join(args)}\n{result.stdout}{result.stderr}")
    return (result.stdout + result.stderr).strip()


def require_root():
    if os.geteuid() != 0:
        raise SystemExit('需要 root：请用 sudo -n python3 deploy/scripts/apply_ios_static.py 执行。')


def require_assets():
    missing = [name for name in ('index.html', 'app.css', 'app.js', 'core.js', 'categories.json',
                                'model-contract.json', 'manifest.webmanifest') if not (WWW / name).is_file()]
    if missing:
        raise SystemExit(f"{WWW} 缺少文件：{', '.join(missing)}；先按 web/ios/README.md 同步静态文件。")


def apply(dry_run):
    text = SITE.read_text(encoding='utf-8')
    block = BLOCK.format(root=WWW)
    if ANCHOR not in text:
        raise SystemExit(f'在 {SITE} 中找不到锚点 `{ANCHOR}`，请人工确认配置结构。')

    if START in text:
        head, _, tail = text.partition(START)
        current, separator, remainder = tail.partition(ANCHOR)
        if not separator:
            raise SystemExit(f'已插入的 /ios 片段结构不完整（缺少锚点），请人工确认 {SITE}。')
        existing = START + current
        if existing == block:
            print(f'/ios 配置已是最新，无需修改。当前哈希 {digest(SITE)}')
            return 0
        updated = head + block + ANCHOR + remainder
        action = '更新'
    else:
        updated = text.replace(ANCHOR, block + ANCHOR, 1)
        action = '新增'

    if dry_run:
        print(f'将{action} /ios 配置到 {SITE}（当前哈希 {digest(SITE)}）:\n')
        print(block)
        return 0

    require_root()
    require_assets()
    before = digest(SITE)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = BASE / 'shared' / f'nginx-mobile-cloud-backend-pre-ios-{stamp}.conf'
    shutil.copy2(SITE, backup)
    print(f'已备份原配置到 {backup}（sha256 {before}）')

    SITE.write_text(updated, encoding='utf-8')
    after = digest(SITE)
    try:
        command(['nginx', '-t'])
    except SystemExit as error:
        shutil.copy2(backup, SITE)
        raise SystemExit(f'nginx -t 未通过，已恢复原配置。\n{error}')
    try:
        command(['systemctl', 'reload', 'nginx'])
    except SystemExit as error:
        shutil.copy2(backup, SITE)
        command(['systemctl', 'reload', 'nginx'])
        raise SystemExit(f'reload 失败，已恢复原配置并重新加载。\n{error}')
    print(f'{action}完成，nginx -t 通过并已 reload。配置哈希 {before} → {after}')
    print(f'回退：sudo -n cp {backup} {SITE} && sudo -n nginx -t && sudo -n systemctl reload nginx')
    return 0


def main():
    parser = argparse.ArgumentParser(description='为 /ios 网页版增加 nginx 静态托管 location。')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要插入的配置片段，不修改文件。')
    parser.add_argument('--no-lock', action='store_true', help='不使用 ACME 共享锁（仅调试）。')
    args = parser.parse_args()

    if args.dry_run or args.no_lock:
        return apply(args.dry_run)
    lock_file = open(ACME_LOCK, 'r+')
    with lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return apply(args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
