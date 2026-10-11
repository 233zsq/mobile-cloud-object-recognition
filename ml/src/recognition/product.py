"""Bounded downloads from explicitly selected public product-image URLs.

Discovery is separate: input is a UTF-8 TSV of image URL and product-page URL.
Product photographs carry no assumed license and always enter the review queue.
"""
import csv
import hashlib
import io
import time
import urllib.parse
from pathlib import Path

from PIL import Image, ImageOps

from . import collect
from .common import ROOT, digest, now, read_csv, write_csv, write_json
from .data import heldout_test_rows, phash

IMAGE_HOSTS = frozenset(('cbu01.alicdn.com', 'img.alicdn.com', 'qna.smzdm.com',
                         'am.zdmimg.com', 'pic1.zhimg.com', 'gd-hbimg.huaban.com'))
RIGHTS = 'unverified (product photo; permission not established)'
FILE_LIMIT = 5 * 1024**2
ROUND_LIMIT = 128 * 1024**2


def checked_urls(image, page):
    for value in (image, page):
        parsed = urllib.parse.urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or value.count('https://') != 1
                or len(value) > 8000):
            raise ValueError('Expected a single HTTPS public source URL')
    if urllib.parse.urlsplit(image).hostname not in IMAGE_HOSTS:
        raise ValueError('Image host is outside the observed product-image allowlist')
    return image, page


def collect_products(sources, output, *, max_new=60):
    if type(max_new) is not int or not 1 <= max_new <= 120:
        raise ValueError('max-new must be 1..120')
    manifest = ROOT / 'data/manifests/web-product-candidates.csv'
    rows = read_csv(manifest) if manifest.exists() else []
    ids = {r['source_id'] for r in rows}
    known_hashes = collect.known_photo_hashes()
    # Read only frozen/reserved manifest identities; never decode test photos.
    heldout_hashes, heldout_phashes = set(), set()
    for row in heldout_test_rows():
        heldout_hashes.update(row[f] for f in ('image_sha256', 'parent_image_sha256') if row.get(f))
        heldout_phashes.update(int(row[f], 16) for f in ('phash', 'parent_phash') if row.get(f))
    report = {'purpose': 'product_photo_candidates', 'category': 'pencil_case',
              'discovery': 'Bing Images, user-selected results', 'started_at': now(),
              'rights_status': RIGHTS, 'max_new': max_new, 'download_bytes': 0,
              'downloaded': 0, 'skipped': [], 'failures': []}
    selected, failures = [], 0
    with Path(sources).open(encoding='utf-8-sig', newline='') as stream:
        pairs = list(csv.reader(stream, delimiter='\t'))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)

    def save():
        write_csv(manifest, rows)
        write_csv(output / 'candidates.csv', selected)
        write_json(output / 'collection.json', report)

    # A rerun packages the same observed increment without downloading it again.
    by_id = {r['source_id']: r for r in rows}
    for pair in pairs:
        if len(selected) >= max_new or report['download_bytes'] >= ROUND_LIMIT or failures >= 8:
            break
        image = pair[0] if pair else ''
        try:
            if len(pair) != 2:
                raise ValueError('Expected two TSV columns')
            image, page = checked_urls(*pair)
            identity = hashlib.sha256(image.encode()).hexdigest()[:24]
            if identity in ids:
                cached = by_id[identity]
                path = (ROOT / cached['image_path']).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file() or digest(path) != cached['image_sha256']:
                    raise ValueError('Previously downloaded product photo is missing or changed')
                if cached['image_sha256'] in heldout_hashes or any(
                        (int(cached['phash'], 16) ^ p).bit_count() <= 6 for p in heldout_phashes):
                    raise ValueError('Previously downloaded photo now has a reserved test identity')
                if cached not in selected:
                    selected.append(cached)
                continue
            limit = min(FILE_LIMIT, ROUND_LIMIT - report['download_bytes'])
            blob = collect.fetch(image, limit, retries=1)
            report['download_bytes'] += len(blob)
            sha = hashlib.sha256(blob).hexdigest()
            if sha in known_hashes or sha in heldout_hashes:
                report['skipped'].append({'url': image, 'reason': 'duplicate or reserved photo SHA-256'})
                failures = 0
                continue
            with Image.open(io.BytesIO(blob)) as original:
                if original.format not in ('JPEG', 'PNG', 'WEBP') or getattr(original, 'n_frames', 1) != 1:
                    raise ValueError('Expected a static JPEG/PNG/WEBP photograph')
                if original.width * original.height > 16_000_000 or min(original.size) < 128:
                    raise ValueError('Image dimensions outside 128px..16MP bounds')
                suffix = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[original.format]
                im = ImageOps.exif_transpose(original).convert('RGB')
                im.load()
                signature = phash(im)
                width, height = im.size
            if any((int(signature, 16) ^ p).bit_count() <= 6 for p in heldout_phashes):
                report['skipped'].append({'url': image, 'reason': 'near a reserved test-photo identity'})
                failures = 0
                continue
            path = ROOT / 'data/raw/web_product/pencil_case' / (identity + suffix)
            collect.store_download(path, blob, 'pencil_case', class_cap=750)
            row = {'sample_id': 'product-' + identity, 'image_path': path.relative_to(ROOT).as_posix(),
                   'image_sha256': sha, 'category_id': '3', 'object_id': '',
                   'session_id': 'product-discovery-' + now()[:10], 'collector': 'bing-discovery',
                   'review_status': 'pending', 'source_dataset': 'web_product', 'source_id': identity,
                   'source_url': page, 'original_url': image, 'download_url': image,
                   'author': '', 'license': RIGHTS, 'license_url': '',
                   'group_id': 'product-page-' + hashlib.sha256(page.encode()).hexdigest()[:24],
                   'phash': signature, 'width': str(width), 'height': str(height), 'downloaded_at': now(),
                   'source_version': 'Bing Images discovery; product rights unverified',
                   'review_reason': 'Candidate only; confirm real pencil case, dominant subject and duplicates'}
            rows.append(row); selected.append(row); by_id[identity] = row
            ids.add(identity); known_hashes.add(sha)
            report['downloaded'] += 1
            failures = 0
            save()
            print(f'Product candidates: {len(selected)}; bytes: {report["download_bytes"]}', flush=True)
            time.sleep(.3)
        except Exception as error:
            report['failures'].append({'url': image, 'reason': type(error).__name__ + ': ' + str(error)[:180]})
            failures += 1
            if 'quota reached' in str(error):
                break
    report.update(finished_at=now(), candidate_count=len(selected),
                  stopped_after_consecutive_failures=failures >= 8)
    save()
    return report
