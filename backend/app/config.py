"""Read configuration without modifying the process environment."""

import os
from pathlib import Path
import re

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _integer(values: dict, name: str, default: int, maximum: int | None = None) -> int:
    try:
        value = int(values.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 1 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside the allowed range")
    return value


def load_config(env_file: str | Path | None = None) -> dict:
    path = Path(env_file) if env_file is not None else PROJECT_ROOT / ".env"
    values = {**dotenv_values(path, interpolate=False), **os.environ}
    debug = str(values.get("APP_DEBUG", "false")).strip().lower()
    if debug not in {"true", "false", "1", "0"}:
        raise ValueError("APP_DEBUG must be true, false, 1 or 0")
    level = str(values.get("LOG_LEVEL", "INFO")).strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be a standard logging level")
    host = str(values.get("SERVER_HOST", "127.0.0.1")).strip()
    if not host:
        raise ValueError("SERVER_HOST must not be empty")

    model_dir = values.get("MODEL_DIR")
    if model_dir:
        model_path = Path(model_dir)
        model_dir = str(
            model_path if model_path.is_absolute() else PROJECT_ROOT / model_path
        )

    inference_socket = values.get("INFERENCE_SOCKET", "")
    if inference_socket and not Path(inference_socket).is_absolute():
        raise ValueError("INFERENCE_SOCKET must be an absolute path")
    inference_version = values.get("INFERENCE_MODEL_VERSION", "campus-gpu-v1")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", inference_version):
        raise ValueError("INFERENCE_MODEL_VERSION is invalid")
    inference_sha256 = values.get("INFERENCE_MODEL_SHA256", "a58ca2be234d0d7e7db6bdec3853b3e077df6a88321da4f6bd7a8a5d5be51d13")
    if not re.fullmatch(r"[0-9a-f]{64}", inference_sha256):
        raise ValueError("INFERENCE_MODEL_SHA256 must be a lowercase SHA-256")

    return {
        "DEBUG": debug in {"true", "1"},
        "APP_VERSION": values.get("APP_VERSION", "0.1.0"),
        "LOG_LEVEL": level,
        "SERVER_HOST": host,
        "SERVER_PORT": _integer(values, "SERVER_PORT", 8080, 65535),
        "MAX_CONTENT_LENGTH": _integer(values, "MAX_CONTENT_LENGTH", 10 * 1024 * 1024),
        # MySQL connectivity; authentication and inference remain reserved.
        "DB_HOST": values.get("DB_HOST", "127.0.0.1"),
        "DB_PORT": _integer(values, "DB_PORT", 3306, 65535),
        "DB_NAME": values.get("DB_NAME", "object_recognition"),
        "DB_USER": values.get("DB_USER", "object_recognition"),
        "DB_PASSWORD": values.get("DB_PASSWORD", ""),
        "API_TOKEN": values.get("API_TOKEN", ""),
        "MODEL_DIR": model_dir,
        "INFERENCE_SOCKET": inference_socket,
        "INFERENCE_MODEL_VERSION": inference_version,
        "INFERENCE_MODEL_SHA256": inference_sha256,
        "INFERENCE_TIMEOUT_SECONDS": _integer(values, "INFERENCE_TIMEOUT_SECONDS", 15, 25),
        "INFERENCE_MAX_IMAGE_BYTES": _integer(values, "INFERENCE_MAX_IMAGE_BYTES", 8 * 1024 * 1024, 8 * 1024 * 1024),
    }
