"""Finite rounds scoped to a previously imported local public archive."""

import csv
import io
import json
import os
import zipfile
from .. import ai_review as ai, ai_triage as domain


class RoundError(ValueError):
    """A local round violates its explicit scope or progress-file contract."""


def run_round(db, data, categories, config, actor, archive, max_photos, progress):
    domain.administrator(db, actor)
    if progress.exists() or not progress.resolve().is_relative_to(data.resolve()):
        raise RoundError(
            "Use a new progress file inside the private review data directory"
        )
    with zipfile.ZipFile(archive) as package:
        if (
            package.getinfo("samples.csv").file_size > 8 * 1024**2
            or package.getinfo("queue.json").file_size > 2 * 1024**2
        ):
            raise RoundError("Oversize public queue manifest")
        receipt = json.loads(package.read("queue.json"))
        raw = package.read("samples.csv")
        if (
            receipt.get("purpose") != "public_review_queue"
            or ai.digest(raw) != receipt["files"]["samples.csv"]
        ):
            raise RoundError("Public queue identity differs")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not 1 <= len(rows) <= 2000 or len(rows) != receipt["count"]:
        raise RoundError("Round needs 1..2000 candidate photos")
    scope = []
    for row in rows:
        current = db.execute(
            "SELECT id,category,source_meta FROM samples WHERE sha256=?",
            (row["image_sha256"],),
        ).fetchone()
        if (
            current
            and str(current["category"]) == row["category_id"]
            and json.loads(current["source_meta"]).get("sample_id") == row["sample_id"]
        ):
            scope.append(current["id"])
    if not scope:
        raise RoundError("Import this public queue before starting its round")
    result = {
        "state": "running",
        "photo_limit": max_photos,
        "scope_count": len(scope),
        "processed": 0,
        "counts": {},
        "jobs": [],
        "started_at": ai.stamp(),
        "sample_scope_sha256": ai.digest(json.dumps(sorted(scope)).encode()),
    }

    def save():
        result["updated_at"] = ai.stamp()
        temporary = progress.with_suffix(".new")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(progress)

    save()
    try:
        while result["processed"] < min(max_photos, len(scope)):
            identity = domain.new_job(
                db, actor, min(50, max_photos - result["processed"]), config, True
            )
            report = domain.run_job(
                db, data, categories, config, identity, sample_ids=scope
            )
            result["jobs"].append(identity)
            result["processed"] += len(report["samples"])
            for key, value in report["counts"].items():
                result["counts"][key] = result["counts"].get(key, 0) + value
            save()
            if report["state"] != "done":
                result.update(state="stopped", error_code=report["error_code"])
                break
            if not report["samples"]:
                result["state"] = "scope_exhausted"
                break
        else:
            result["state"] = "done"
    except Exception as error:
        result.update(state="stopped", error_code=type(error).__name__)
    finally:
        result["usage"] = ai.usage_report(ai.usage_totals(db))
        save()
    return result
