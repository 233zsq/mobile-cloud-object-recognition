"""Standard-library I/O shared by legacy collection and formal dataset workflows."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time

LEGACY_FIELDS = [
    "sample_id",
    "image_path",
    "image_sha256",
    "category_id",
    "object_id",
    "session_id",
    "collector",
    "captured_at",
    "split_name",
    "review_status",
    "data_version",
]
FIELDS = [
    *LEGACY_FIELDS,
    "source_dataset",
    "source_id",
    "source_url",
    "original_url",
    "download_url",
    "author",
    "license",
    "license_url",
    "group_id",
    "review_reason",
    "phash",
    "width",
    "height",
    "downloaded_at",
    "source_version",
]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_csv(path, *, fields=None, strip=False):
    """Generic CSV reads preserve values; the legacy adapter opts into its strict schema."""
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if fields is not None and reader.fieldnames != fields:
            raise ValueError(f"表头与模板不一致：{reader.fieldnames}，应为 {fields}")
        rows = []
        for number, row in enumerate(reader, start=2):
            if fields is not None and (
                None in row or any(value is None for value in row.values())
            ):
                raise ValueError(f"第{number}行字段数量与表头不一致")
            rows.append(
                {key: value.strip() for key, value in row.items()} if strip else row
            )
    return rows


def read_legacy_manifest(path):
    return read_csv(path, fields=LEGACY_FIELDS, strip=True)


def replace_file(temporary, destination):
    """Retain the formal workflow's retry behavior for Windows reader handles."""
    for attempt in range(7):
        try:
            temporary.replace(destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 6:
                raise
            time.sleep(0.05 * 2**attempt)


def atomic_write(path, write, *, newline=None, replace=replace_file):
    """Serialize completely in the destination directory before replacing a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline=newline,
            dir=path.parent,
            prefix="." + path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.chmod(0o600)
            temporary.unlink()


def write_csv(path, rows, fields=FIELDS):
    """Formal CSV output keeps its ordered projection and blank defaults."""

    def serialize(stream):
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)

    atomic_write(path, serialize, newline="")


def write_legacy_manifest(path, rows):
    def serialize(stream):
        writer = csv.DictWriter(stream, fieldnames=LEGACY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    atomic_write(
        path,
        serialize,
        newline="",
        replace=lambda temporary, destination: temporary.replace(destination),
    )


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    atomic_write(path, lambda stream: stream.write(content))
