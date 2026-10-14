"""Register immutable local candidate comparisons against the frozen baseline."""

import json
import re
from werkzeug.exceptions import abort
from ..database import append_event
from ..utils import sha, stamp
from ..validation import safe


class CandidateError(ValueError):
    """A candidate conflicts with the frozen baseline or a prior registration."""


def register_candidate(connection, baseline, report_file):
    """Import a locally verified comparison, never execute training on cloud."""
    report_bytes = report_file.read_bytes()
    report = json.loads(report_bytes)
    candidate_meta = report["candidate"]
    version = safe(candidate_meta["model_version"])
    if (
        report.get("purpose") != "evolution_comparison"
        or report.get("status") != "pending_human_approval"
        or report["baseline"]["sha256"] != baseline["sha256"]
        or candidate_meta["status"] != "frozen"
        or candidate_meta["sha256"] == baseline["sha256"]
    ):
        raise CandidateError(
            "A verified distinct frozen candidate and matching baseline are required"
        )
    if not re.fullmatch("[0-9a-f]{64}", candidate_meta["sha256"]):
        raise CandidateError("Invalid candidate hash")
    existing = connection.execute(
        "SELECT digest FROM candidates WHERE version=?", (version,)
    ).fetchone()
    if existing:
        if existing["digest"] != sha(report_bytes):
            raise CandidateError("Candidate version is immutable")
        return
    connection.execute(
        "INSERT INTO candidates(version,report,digest,created_at) VALUES(?,?,?,?)",
        (version, report_bytes.decode(), sha(report_bytes), stamp()),
    )
    return version


def candidate(connection, version):
    row = connection.execute(
        "SELECT * FROM candidates WHERE version=?", (version,)
    ).fetchone()
    if not row:
        abort(404)
    return row


def decide_candidate(connection, actor, version, digest, choice, reason):
    if choice not in ("approved", "rejected"):
        abort(400)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            "SELECT * FROM candidates WHERE version=?", (version,)
        ).fetchone()
        if not row or row["digest"] != digest or row["status"] != "pending":
            abort(409, "候选记录已变化或已经审批")
        connection.execute(
            "UPDATE candidates SET status=?,decision=? WHERE version=?",
            (choice, reason, version),
        )
        append_event(
            connection,
            actor,
            "model_" + choice,
            version,
            {
                "report_sha256": row["digest"],
                "model_sha256": json.loads(row["report"])["candidate"]["sha256"],
                "reason": reason,
            },
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def approval_receipt(connection, version):
    row = connection.execute(
        "SELECT * FROM candidates WHERE version=?", (version,)
    ).fetchone()
    if not row or row["status"] != "approved":
        abort(409, "此模型尚未批准")
    record = connection.execute(
        "SELECT e.*,u.username FROM events e JOIN users u ON e.actor=u.id WHERE action='model_approved' AND subject=? ORDER BY e.id DESC LIMIT 1",
        (version,),
    ).fetchone()
    return {
        "model_version": version,
        "model_sha256": json.loads(row["report"])["candidate"]["sha256"],
        "status": "approved",
        "report_sha256": row["digest"],
        "approved_by": record["username"],
        "approved_at": record["created_at"],
        "reason": row["decision"],
    }
