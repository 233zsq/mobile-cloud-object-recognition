"""Freeze reviewed training batches and verify downloadable archive identity."""

import csv
import io
import json
import zipfile
from werkzeug.exceptions import abort
from .. import ai_triage
from ..assets import SOURCE_FIELDS, crop_box
from ..database import append_event
from ..utils import encode, file_sha, sha, stamp
from ..validation import safe


def freeze_batch(connection, data, categories, category_bytes, actor, batch_id):
    connection.execute("BEGIN IMMEDIATE")
    try:
        if ai_triage.pending_approval_audits(connection):
            abort(409, "请先完成AI自动通过照片抽检，再冻结训练批次")
        rows = connection.execute(
            "SELECT s.*,u.username FROM samples s JOIN users u ON s.owner=u.id WHERE s.status='approved' AND s.batch IS NULL ORDER BY s.id"
        ).fetchall()
        if not rows:
            abort(400, "没有待冻结的已通过照片")
        if connection.execute(
            "SELECT 1 FROM batches WHERE id=?", (batch_id,)
        ).fetchone():
            abort(409, "批次版本已存在")
        labels = {}
        for row in rows:
            for field in ("object_id", "group_id"):
                if row[field]:
                    labels.setdefault((field, row[field]), set()).add(row["category"])
        if any(len(values) > 1 for values in labels.values()):
            abort(409, "同一实物或重复组出现多个类别，请先复核标签")
        manifests = []
        for row in rows:
            if file_sha(data / "images" / row["filename"]) != row["sha256"]:
                abort(409, "原照片哈希发生变化，冻结中止")
            manifests.append(
                {
                    "sample_id": row["id"],
                    "image_path": "images/" + row["filename"],
                    "image_sha256": row["sha256"],
                    "category_id": row["category"],
                    "object_id": row["object_id"],
                    "session_id": row["session_id"],
                    "group_id": row["group_id"],
                    "phash": row["phash"],
                    "collector": row["username"],
                    "captured_at": row["created_at"]
                    if row["source"] == "field"
                    else "",
                    "review_status": "approved",
                    "review_reason": row["reason"],
                    **{
                        key: json.loads(row["source_meta"]).get(key, "")
                        for key in SOURCE_FIELDS
                        if key != "previous_review_reason"
                    },
                    "source_dataset": row["source"],
                    "source_sample_id": json.loads(row["source_meta"]).get(
                        "sample_id", ""
                    ),
                    "crop_box": json.dumps(
                        crop_box(row["crop"], row["width"], row["height"])
                    )
                    if row["crop"]
                    else "",
                    "width": row["width"],
                    "height": row["height"],
                }
            )
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(manifests[0]))
        writer.writeheader()
        writer.writerows(manifests)
        manifest_bytes = stream.getvalue().encode("utf-8")
        receipt = {
            "schema_version": 1,
            "purpose": "training_only",
            "batch_id": batch_id,
            "created_at": stamp(),
            "category_version": categories["category_version"],
            "categories_sha256": sha(category_bytes),
            "ai_review_provenance": ai_triage.provenance(connection, rows),
            "count": len(rows),
            "files": {
                "samples.csv": sha(manifest_bytes),
                **{r["image_path"]: r["image_sha256"] for r in manifests},
            },
        }
        archive = data / "batches" / (batch_id + ".zip")
        temp = archive.with_suffix(".tmp")
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED) as package:
            package.writestr("batch.json", encode(receipt))
            package.writestr("samples.csv", manifest_bytes)
            for row in rows:
                package.write(
                    data / "images" / row["filename"], "images/" + row["filename"]
                )
        temp.replace(archive)
        receipt["archive_sha256"] = file_sha(archive)
        connection.execute(
            "INSERT INTO batches VALUES(?,?,?)",
            (batch_id, encode(receipt).decode(), stamp()),
        )
        connection.executemany(
            "UPDATE samples SET batch=?,revision=revision+1 WHERE id=?",
            [(batch_id, r["id"]) for r in rows],
        )
        connection.execute(
            "DELETE FROM review_leases WHERE sample_id IN (SELECT id FROM samples WHERE batch=?)",
            (batch_id,),
        )
        append_event(connection, actor, "freeze", batch_id, receipt)
        connection.commit()
        return receipt
    except Exception:
        connection.rollback()
        raise


def batch_archive(connection, data, version):
    row = connection.execute(
        "SELECT * FROM batches WHERE id=?", (safe(version),)
    ).fetchone()
    if not row:
        abort(404)
    archive = data / "batches" / (version + ".zip")
    if file_sha(archive) != json.loads(row["receipt"])["archive_sha256"]:
        abort(409, "批次包哈希错误")
    return archive
