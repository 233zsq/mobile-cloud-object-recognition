"""Charge only transmitted response bytes, including range requests."""

from flask import abort, current_app, request, send_file
from .database import db


def budgeted_file(path, **kwargs):
    response = send_file(path, conditional=True, **kwargs)
    size = response.content_length or 0
    if request.method != "HEAD" and response.status_code in (200, 206) and size:
        db().execute("BEGIN IMMEDIATE")
        changed = (
            db()
            .execute(
                "UPDATE egress SET bytes=bytes+? WHERE id=1 AND bytes+?<=?",
                (size, size, current_app.config["EGRESS_LIMIT_BYTES"]),
            )
            .rowcount
        )
        if not changed:
            db().rollback()
            response.close()
            abort(429, "审核资源累计流量预算已用完，请联系管理员核对服务器余量")
        db().commit()
    return response
