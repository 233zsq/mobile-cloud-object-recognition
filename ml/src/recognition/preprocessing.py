"""Portable float32 half-pixel bilinear resize and grey letterbox."""
import math
import numpy as np
from PIL import Image, ImageOps

SPEC = {"version": "rgb-letterbox-v1", "orientation": "EXIF transpose", "color_order": "RGB", "shape": [1, 224, 224, 3], "dtype": "float32", "pixel_range": [0, 255], "crop": "none", "resize": "bilinear half_pixel_centers; antialias=false; round half up", "padding": "center; RGB 128; odd remainder right/bottom", "normalization": "inside model: x / 127.5 - 1", "byte_order": "little-endian"}


def bilinear(array, height, width):
    ih, iw = array.shape[:2]
    y = np.clip((np.arange(height, dtype=np.float32) + .5) * ih / height - .5, 0, ih - 1)
    x = np.clip((np.arange(width, dtype=np.float32) + .5) * iw / width - .5, 0, iw - 1)
    y0, x0 = np.floor(y).astype(int), np.floor(x).astype(int)
    y1, x1 = np.minimum(y0 + 1, ih - 1), np.minimum(x0 + 1, iw - 1)
    fy, fx = (y - y0)[:, None, None], (x - x0)[None, :, None]
    top = array[y0[:, None], x0[None, :]] * (1 - fx) + array[y0[:, None], x1[None, :]] * fx
    bottom = array[y1[:, None], x0[None, :]] * (1 - fx) + array[y1[:, None], x1[None, :]] * fx
    return (top * (1 - fy) + bottom * fy).astype(np.float32)


def preprocess(path):
    with Image.open(path) as original:
        corrected=ImageOps.exif_transpose(original)
        if "A" in corrected.getbands() or "transparency" in corrected.info:
            rgba=corrected.convert("RGBA")
            corrected=Image.alpha_composite(Image.new("RGBA",rgba.size,(128,128,128,255)),rgba)
        array = np.asarray(corrected.convert("RGB"), dtype=np.float32)
    h, w = array.shape[:2]
    scale = 224 / max(h, w)
    nh, nw = max(1, math.floor(h * scale + .5)), max(1, math.floor(w * scale + .5))
    result = np.full((224, 224, 3), 128, dtype=np.float32)
    top, left = (224 - nh) // 2, (224 - nw) // 2
    result[top:top+nh, left:left+nw] = bilinear(array, nh, nw)
    return result


def augment(array, rng):
    """Apply training-only modest affine geometry and brightness."""
    angle = rng.uniform(-10, 10) * np.pi / 180
    scale = rng.uniform(.9, 1.1)
    c, s = np.cos(angle) / scale, np.sin(angle) / scale
    tx, ty = rng.uniform(-11.2, 11.2, 2)
    matrix = (c, s, 111.5 - c * (111.5 + tx) - s * (111.5 + ty), -s, c, 111.5 + s * (111.5 + tx) - c * (111.5 + ty))
    # Geometry is uint8 for training only; deployment uses float32 bilinear above.
    im = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).transform((224, 224), Image.Transform.AFFINE, matrix, Image.Resampling.BILINEAR, fillcolor=(128,128,128))
    return np.clip(np.asarray(im, dtype=np.float32) * rng.uniform(.85, 1.15), 0, 255)
