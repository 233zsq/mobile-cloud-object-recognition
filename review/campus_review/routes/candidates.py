"""HTTP adapters for candidates review operations; endpoint names stay stable."""

import io
import json
from flask import g, redirect, render_template, request, send_file, url_for
from ..database import db
from ..services.candidates import (
    approval_receipt,
    candidate as get_candidate,
    decide_candidate,
)
from ..security import require
from ..utils import encode
from ..validation import text


@require()
def candidate(version):
    row = get_candidate(db(), version)
    return render_template(
        "candidate.html", candidate=row, report=json.loads(row["report"])
    )


@require()
def candidate_report(version):
    row = get_candidate(db(), version)
    return send_file(
        io.BytesIO(row["report"].encode()),
        mimetype="application/json",
        as_attachment=True,
        download_name=version + "-comparison.json",
    )


@require("admin")
def decision(version):
    choice, reason = request.form.get("decision"), text("reason")
    decide_candidate(
        db(), g.user["id"], version, request.form.get("digest"), choice, reason
    )
    return redirect(url_for("candidate", version=version))


@require("admin")
def approval(version):
    receipt = approval_receipt(db(), version)
    return send_file(
        io.BytesIO(encode(receipt)),
        mimetype="application/json",
        as_attachment=True,
        download_name=version + "-approval.json",
    )


def register(app):
    app.add_url_rule("/candidates/<version>", view_func=candidate, methods=["GET"])
    app.add_url_rule(
        "/candidates/<version>/report.json", view_func=candidate_report, methods=["GET"]
    )
    app.add_url_rule(
        "/candidates/<version>/decision", view_func=decision, methods=["POST"]
    )
    app.add_url_rule(
        "/candidates/<version>/approval.json", view_func=approval, methods=["GET"]
    )
