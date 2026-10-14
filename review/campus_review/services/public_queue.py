"""Bounded local public-queue imports; every new photo remains pending."""

import csv
import io
import json
import secrets
import zipfile
from pathlib import Path
from PIL import Image
from werkzeug.security import generate_password_hash
from ..assets import source_metadata
from ..utils import sha, stamp
from ..validation import safe
from .photos import store_photo


class PublicQueueError(ValueError):
    """A local queue violates the frozen identity or import budget."""


def import_queue(
    connection, data, queue_category_hashes, archive_file, progress=lambda message: None
):
    """Import bounded, locally collected sources as pending; no remote URL fetch."""
    summary = {"imported": 0, "skipped_existing": 0, "rejected": [], "at": stamp()}
    with zipfile.ZipFile(archive_file) as package:
        infos = package.infolist()
        names = [i.filename for i in infos]
        if (
            len(names) != len(set(names))
            or len(names) > 3002
            or sum(i.file_size for i in infos) > 3 * 1024**3
        ):
            raise PublicQueueError("Public archive budget exceeded")
        if any(
            i.file_size > 8 * 1024**2
            or i.filename.startswith("/")
            or "\\" in i.filename
            or ".." in Path(i.filename).parts
            for i in infos
        ):
            raise PublicQueueError("Unsafe public archive path or size")
        receipt = json.loads(package.read("queue.json"))
        if (
            receipt.get("purpose") != "public_review_queue"
            or receipt.get("categories_sha256") not in queue_category_hashes
        ):
            raise PublicQueueError("Public queue purpose/categories differ")
        if (
            set(names) != {"queue.json", *receipt["files"]}
            or sha(package.read("samples.csv")) != receipt["files"]["samples.csv"]
        ):
            raise PublicQueueError("Public queue file identity differs")
        rows = list(
            csv.DictReader(io.StringIO(package.read("samples.csv").decode("utf-8-sig")))
        )
        if len(rows) != receipt["count"] or set(receipt["files"]) != {
            "samples.csv",
            *[r["image_path"] for r in rows],
        }:
            raise PublicQueueError("Public queue manifest differs")
        owner = connection.execute(
            "SELECT id FROM users WHERE username='@public-import' AND active=0"
        ).fetchone()
        if not owner:
            connection.execute(
                "INSERT INTO users(username,password,role,active) VALUES(?,?,'reviewer',0)",
                ("@public-import", generate_password_hash(secrets.token_urlsafe(32))),
            )
            owner = connection.execute(
                "SELECT id FROM users WHERE username='@public-import'"
            ).fetchone()
        for index, row in enumerate(rows):
            try:
                path = Path(row["image_path"])
                if (
                    len(path.parts) != 2
                    or path.parts[0] != "images"
                    or int(row["category_id"]) not in range(10)
                ):
                    raise ValueError("Invalid image path/category")
                content = package.read(row["image_path"])
                if (
                    sha(content) != row["image_sha256"]
                    or sha(content) != receipt["files"][row["image_path"]]
                ):
                    raise ValueError("Public photo hash differs")
                if connection.execute(
                    "SELECT 1 FROM samples WHERE sha256=?", (row["image_sha256"],)
                ).fetchone():
                    summary["skipped_existing"] += 1
                    continue
                meta = source_metadata(row)
                meta["sample_id"] = safe(row["sample_id"])
                object_id, group_id = (
                    row.get("object_id", ""),
                    row.get("group_id") or row["sample_id"],
                )
                if len(object_id) > 160 or len(group_id) > 160:
                    raise ValueError("Identity too long")
                store_photo(
                    connection,
                    data,
                    content,
                    int(row["category_id"]),
                    object_id,
                    "public-collection",
                    group_id,
                    owner["id"],
                    meta,
                )
                summary["imported"] += 1
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                summary["rejected"].append(
                    {"sample_id": row.get("sample_id"), "reason": str(exc)[:180]}
                )
            if (index + 1) % 100 == 0:
                progress(f"Processed {index + 1}/{len(rows)}")
    return summary
