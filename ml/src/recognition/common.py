"""Versioned configuration, manifests and artifact identities."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .manifest_io import (
    FIELDS as FIELDS,
    digest as digest,
    read_csv as read_csv,
    read_json as read_json,
    replace_file as replace_file,
    time as time,
    write_csv as write_csv,
    write_json as write_json,
)

ROOT = Path(
    os.environ.get("RECOGNITION_ROOT", Path(__file__).resolve().parents[3])
).resolve()
TZ = timezone(timedelta(hours=8))
EXPECTED_LABELS = (
    "cup",
    "umbrella",
    "book",
    "pencil_case",
    "mouse",
    "keyboard",
    "earphones",
    "charger",
    "key",
    "backpack",
)


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def image_path(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Sample path must stay inside repository")
    return path


def category_path(version=None):
    current = ROOT / "shared/categories.json"
    if version is None:
        return current
    safe_name(version)
    archived = ROOT / "shared/category-versions" / (version + ".json")
    if archived.is_file():
        return archived
    # Historical workspaces may contain only the baseline alias; keep them reproducible.
    if read_json(current)["category_version"] == version:
        return current
    return archived


def categories(version=None):
    value = read_json(category_path(version))
    if version is not None and value["category_version"] != version:
        raise ValueError("Category archive version mismatch")
    items = value["categories"]
    if value.get("status") != "frozen" or [x["id"] for x in items] != list(range(10)):
        raise ValueError("Expected frozen category IDs 0..9")
    if len({x["label_key"] for x in items}) != 10:
        raise ValueError("Duplicate label key")
    if tuple(x["label_key"] for x in items) != EXPECTED_LABELS:
        raise ValueError(
            "Frozen category label order differs from the ten-class contract"
        )
    return value


def code_commit():
    try:
        # Dataset storage may be elsewhere via RECOGNITION_ROOT; identify source.
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def safe_name(value):
    if not value or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for c in value
    ):
        raise ValueError(
            "Version/experiment ID must contain only letters, numbers, _ or -"
        )
    return value
