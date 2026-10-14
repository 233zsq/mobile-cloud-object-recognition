"""Validate and store originals and renditions without HTTP or CLI state."""

import io
import json
import math
import threading
import uuid
from PIL import Image, ImageOps
from ..assets import renditions
from ..utils import sha, stamp

Image.MAX_IMAGE_PIXELS = 16_000_000
IMAGE_LOCK = threading.Lock()


def perceptual(im):
    """DCT pHash compatible with recognition.data.phash, without NumPy on cloud."""
    a = list(ImageOps.exif_transpose(im).convert("L").resize((32, 32)).getdata())
    cosines = [
        [math.cos(math.pi * (n + 0.5) * k / 32) for n in range(32)] for k in range(8)
    ]
    temp = [
        [sum(cosines[k][n] * a[n * 32 + x] for n in range(32)) for x in range(32)]
        for k in range(8)
    ]
    low = [
        sum(temp[k][x] * cosines[j][x] for x in range(32))
        for k in range(8)
        for j in range(8)
    ]
    median = sorted(low[1:])[31]
    return f"{sum((v > median) << i for i, v in enumerate(low)):016x}"


def store_photo(
    connection,
    data,
    content,
    category,
    object_id,
    session_id,
    group_id,
    owner,
    meta=None,
):
    if len(content) > 8 * 1024**2:
        raise ValueError("单张照片最大8MiB")
    identity = sha(content)
    if connection.execute(
        "SELECT 1 FROM samples WHERE sha256=?", (identity,)
    ).fetchone():
        raise ValueError("这张照片已经上传")
    sid = uuid.uuid4().hex
    with IMAGE_LOCK, Image.open(io.BytesIO(content)) as im:
        if (
            im.format not in ("JPEG", "PNG", "WEBP")
            or getattr(im, "n_frames", 1) != 1
            or im.width * im.height > Image.MAX_IMAGE_PIXELS
        ):
            raise ValueError("仅支持1600万像素以内的单帧 JPEG、PNG、WebP")
        im.load()
        corrected = ImageOps.exif_transpose(im).convert("RGB")
        width, height = corrected.size
        if min(width, height) < 128:
            raise ValueError("照片短边至少128像素")
        fingerprint = perceptual(im)
        ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}[im.format]
        renditions(corrected, data, sid)
    filename = sid + ext
    original = data / "images" / filename
    original.write_bytes(content)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO samples(id,owner,filename,sha256,category,object_id,session_id,group_id,phash,width,height,created_at,source,source_meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                owner,
                filename,
                identity,
                category,
                object_id,
                session_id,
                group_id or sid,
                fingerprint,
                width,
                height,
                stamp(),
                meta["source_dataset"] if meta else "field",
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        connection.execute(
            "INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,?,?,?,?)",
            (
                owner,
                "public_import" if meta else "upload",
                sid,
                json.dumps({"sha256": identity, "category": category}),
                stamp(),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        original.unlink(missing_ok=True)
        for name in ("thumbs", "details"):
            (data / name / (sid + ".webp")).unlink(missing_ok=True)
        raise
    return sid
