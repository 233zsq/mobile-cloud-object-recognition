"""Independent Python 3.12 CPU worker. The public Flask app uses a private socket."""

import argparse
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import sys
import tempfile
import threading
import warnings

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_600_000


class ImageError(Exception):
    def __init__(self, code, status):
        self.code, self.status = code, status


def validate_image(path):
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ImageError("IMAGE_TOO_LARGE", 413)
            if image.format not in ("JPEG", "PNG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                raise ImageError("UNSUPPORTED_IMAGE", 415)
            image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageError("IMAGE_TOO_LARGE", 413) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ImageError("INVALID_IMAGE", 400) from exc


class CpuServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 8


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *args):
        pass  # The public API logs request IDs; do not log images or credentials.

    def send_json(self, status, value):
        data = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def error(self, code, status):
        self.send_json(status, {"error": {"code": code}})

    def do_GET(self):
        if self.path != "/health":
            return self.error("NOT_FOUND", 404)
        engine = self.server.engine
        self.send_json(200, {"model_loaded": True, "model_version": engine.model_version,
                            "model_sha256": engine.model_sha256, "model_status": "ready"})

    def do_POST(self):
        if self.path != "/infer":
            return self.error("NOT_FOUND", 404)
        if self.headers.get("X-Model-Version") != self.server.engine.model_version:
            return self.error("MODEL_VERSION_MISMATCH", 409)
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                return self.error("INVALID_IMAGE", 400)
            length = int(lengths[0])
        except ValueError:
            return self.error("INVALID_IMAGE", 400)
        if not 0 < length <= MAX_IMAGE_BYTES:
            return self.error("IMAGE_TOO_LARGE" if length > MAX_IMAGE_BYTES else "INVALID_IMAGE", 413 if length > MAX_IMAGE_BYTES else 400)
        # One image at a time bounds decode memory; excess requests fail without a queue.
        if not self.server.admission.acquire(blocking=False):
            remaining = length
            while remaining:
                block = self.rfile.read(min(remaining, 65536))
                if not block:
                    break
                remaining -= len(block)
            return self.error("INFERENCE_BUSY", 503)
        try:
            data = self.rfile.read(length)
            if len(data) != length:
                return self.error("INVALID_IMAGE", 400)
            with tempfile.TemporaryDirectory(prefix="image-", dir=self.server.temporary_directory) as directory:
                path = Path(directory) / "upload"
                path.write_bytes(data)
                validate_image(path)
                result = self.server.engine.predict_image(path)
            self.send_json(200, result)
        except ImageError as exc:
            self.error(exc.code, exc.status)
        except (OSError, SyntaxError) as exc:
            # Truncated images may open successfully but fail during actual decode.
            print(json.dumps({"event":"inference_failed","error_type":type(exc).__name__}), flush=True)
            self.error("INVALID_IMAGE", 400)
        except Exception as exc:
            print(json.dumps({"event":"inference_failed","error_type":type(exc).__name__}), flush=True)
            self.error("MODEL_UNAVAILABLE", 503)
        finally:
            self.server.admission.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--socket", required=True, type=Path)
    parser.add_argument("--model-version", default="campus-gpu-v1")
    parser.add_argument("--model-sha256", required=True)
    args = parser.parse_args()
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
    sys.path.insert(0, str(args.package.resolve(strict=True)))
    from verify_package import verify_package
    from backend_adapter import CpuModelService
    integrity = verify_package(args.package)
    if integrity["model_version"] != args.model_version or integrity["model_sha256"] != args.model_sha256:
        raise ValueError("Package does not match pinned model identity")
    engine = CpuModelService(args.package / "release", threads=1)
    # Warm the interpreter before accepting requests; no training runtime is loaded.
    import numpy as np
    for _ in range(20):
        engine.runner.predict_tensor(np.full((224,224,3),128,dtype=np.float32))
    path = args.socket
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError("A private absolute runtime socket path is required")
    if path.exists():
        if not stat.S_ISSOCK(path.stat().st_mode):
            raise ValueError("Refusing to replace a non-socket path")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise RuntimeError("Another inference worker is already listening")
    os.umask(0o077)
    with CpuServer(str(path), Handler) as server:
        server.engine = engine
        server.admission = threading.BoundedSemaphore(1)
        server.temporary_directory = path.parent
        print(json.dumps({"event":"model_ready","model_version":engine.model_version,"model_sha256":engine.model_sha256,"threads":1}), flush=True)
        server.serve_forever(poll_interval=0.2)


if __name__ == "__main__":
    main()
