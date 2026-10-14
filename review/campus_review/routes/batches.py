"""HTTP adapters for batches review operations; endpoint names stay stable."""

from ..services.batches import batch_archive, freeze_batch
from flask import g, redirect, url_for
from ..context import resources
from ..database import db
from ..http import budgeted_file
from ..security import require
from ..validation import safe, text


@require("admin")
def freeze():
    runtime = resources()
    freeze_batch(
        db(),
        runtime.data,
        runtime.categories,
        runtime.category_bytes,
        g.user["id"],
        safe(text("version")),
    )
    return redirect(url_for("index", status="approved"))


@require("admin")
def download(version):
    archive = batch_archive(db(), resources().data, version)
    return budgeted_file(archive, as_attachment=True)


def register(app):
    app.add_url_rule("/batches", view_func=freeze, methods=["POST"])
    app.add_url_rule("/batches/<version>.zip", view_func=download, methods=["GET"])
