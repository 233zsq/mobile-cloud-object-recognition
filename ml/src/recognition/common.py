"""Versioned configuration, manifests and artifact identities."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get("RECOGNITION_ROOT", Path(__file__).resolve().parents[3])).resolve()
TZ = timezone(timedelta(hours=8))
EXPECTED_LABELS = ("cup","umbrella","book","pencil_case","mouse","keyboard","earphones","charger","key","backpack")
FIELDS = ["sample_id", "image_path", "image_sha256", "category_id", "object_id", "session_id", "collector", "captured_at", "split_name", "review_status", "data_version", "source_dataset", "source_id", "source_url", "original_url", "download_url", "author", "license", "license_url", "group_id", "review_reason", "phash", "width", "height", "downloaded_at", "source_version"]


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def replace_file(temporary, destination):
    """Keep atomic writes, allowing a Windows reader to release its handle."""
    for attempt in range(7):
        try:
            temporary.replace(destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 6:
                raise
            time.sleep(0.05 * 2 ** attempt)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    replace_file(tmp, path)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=FIELDS):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    replace_file(tmp, path)


def image_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Sample path must stay inside repository")
    return path


def category_path(version=None):
    current = ROOT / "shared/categories.json"
    if version is None or read_json(current)["category_version"] == version:
        return current
    safe_name(version)
    return ROOT / "shared/category-versions" / (version + ".json")


def categories(version=None):
    value = read_json(category_path(version))
    if version is not None and value["category_version"] != version:
        raise ValueError("Category archive version mismatch")
    items = value["categories"]
    if value.get("status") != "frozen" or [x["id"] for x in items] != list(range(10)):
        raise ValueError("Expected frozen category IDs 0..9")
    if len({x["label_key"] for x in items}) != 10:
        raise ValueError("Duplicate label key")
    if tuple(x["label_key"] for x in items)!=EXPECTED_LABELS:
        raise ValueError("Frozen category label order differs from the ten-class contract")
    return value


def code_commit():
    try:
        # Dataset storage may be elsewhere via RECOGNITION_ROOT; identify source.
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[3], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def safe_name(value):
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value):
        raise ValueError("Version/experiment ID must contain only letters, numbers, _ or -")
    return value
