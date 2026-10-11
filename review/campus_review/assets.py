"""Bounded image renditions and source metadata; originals remain immutable."""
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps

PUBLIC_SOURCES = ('wikimedia_commons', 'open_images', 'web_product')
SOURCE_FIELDS = ('source_dataset', 'source_id', 'source_url', 'original_url', 'download_url',
                 'author', 'license', 'license_url', 'downloaded_at', 'source_version',
                 'previous_review_reason')


def source_metadata(row):
    result = {k: str(row.get(k, '')) for k in SOURCE_FIELDS}
    if result['source_dataset'] not in PUBLIC_SOURCES or not all(result[k] for k in
            ('source_id', 'source_url', 'original_url', 'license')):
        raise ValueError('Public photo needs source identity, URLs and license')
    for key, value in result.items():
        if len(value) > 8000:
            raise ValueError('Source metadata too long')
        if key.endswith('_url') and value and (urlsplit(value).scheme not in ('http', 'https') or not urlsplit(value).netloc):
            raise ValueError('Source URLs must use HTTP(S)')
    return result


def renditions(image, directory, sid):
    """Both formats have a byte ceiling, even for noisy source photos."""
    for name, edge, ceiling in (('thumbs', 320, 32 * 1024), ('details', 960, 160 * 1024)):
        copy = image.copy()
        copy.thumbnail((edge, edge))
        while True:
            stream = io.BytesIO()
            copy.save(stream, 'WEBP', quality=76, method=4)
            if len(stream.getvalue()) <= ceiling:
                break
            copy.thumbnail((max(64, copy.width * 4 // 5), max(64, copy.height * 4 // 5)))
        path = Path(directory) / name / (sid + '.webp')
        path.parent.mkdir(exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(stream.getvalue())
        temporary.replace(path)


def crop_box(raw, width, height):
    if not raw:
        return None
    fractions = json.loads(raw)
    if not isinstance(fractions, list) or len(fractions) != 4 or any(type(v) is not int or not 0 <= v <= 10000 for v in fractions):
        raise ValueError('Invalid crop coordinates')
    x0, y0, x1, y1 = fractions
    box = (x0 * width // 10000, y0 * height // 10000,
           (x1 * width + 9999) // 10000, (y1 * height + 9999) // 10000)
    if box[2] - box[0] < 128 or box[3] - box[1] < 128:
        raise ValueError('裁剪区域的原图宽高都需至少128像素')
    return box
