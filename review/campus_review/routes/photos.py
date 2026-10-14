"""HTTP adapters for photos review operations; endpoint names stay stable."""

import json
import sqlite3
from PIL import Image, ImageOps
from .. import ai_review, ai_triage
from ..assets import crop_box, renditions
from ..decisions import CHOICES, initial_choice, resolve_choice
from ..services.photos import IMAGE_LOCK, store_photo
from flask import abort, flash, g, redirect, render_template, request, url_for
from ..context import resources, review_workflow
from ..database import db, event
from ..http import budgeted_file
from ..security import require
from ..utils import sha
from ..validation import safe, text


@require()
def upload():
    data = resources().data
    if request.method == "POST":
        upload_file = request.files.get("image")
        if not upload_file:
            abort(400, "请选择照片")
        category = request.form.get("category", "")
        if category not in {str(i) for i in range(10)}:
            abort(400, "请选择类别")
        object_id, session_id = text("object_id"), text("session_id")
        content = upload_file.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            abort(413, "单张照片最大8MiB")
        identity = sha(content)
        if db().execute("SELECT 1 FROM samples WHERE sha256=?", (identity,)).fetchone():
            abort(409, "这张照片已经上传，请在审核列表中查找")
        try:
            sid = store_photo(
                db(),
                data,
                content,
                int(category),
                object_id,
                session_id,
                text("group_id", False),
                g.user["id"],
            )
        except sqlite3.IntegrityError:
            abort(409, "这张照片已经上传")
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            abort(400, "照片无法接收：" + str(exc))
        return redirect(url_for("sample", sid=sid))
    return render_template("upload.html")


@require()
def image(sid):
    data = resources().data
    row = db().execute("SELECT * FROM samples WHERE id=?", (sid,)).fetchone()
    if not row:
        abort(404)
    size = request.args.get("size", "detail")
    if size not in ("thumb", "detail"):
        abort(400)
    path = data / ("thumbs" if size == "thumb" else "details") / (safe(sid) + ".webp")
    if not path.exists():
        with IMAGE_LOCK, Image.open(data / "images" / row["filename"]) as im:
            renditions(ImageOps.exif_transpose(im).convert("RGB"), data, sid)
    return budgeted_file(path, mimetype="image/webp")


@require()
def sample(sid):
    cat = resources().categories
    work = review_workflow()
    filters = work.filters(request.args)
    row = work.sample(sid)
    if request.method == "POST":
        if row["batch"]:
            abort(409, "照片已冻结，不能修改")
        if not work.allowed(row):
            abort(403, "该品类由其他成员负责，请联系管理员调整分工")
        intent = request.form.get("action", "save")
        if intent not in ("save", "next"):
            abort(400, "未知审核操作")
        status, reason = resolve_choice(
            request.form.get("decision"),
            request.form.get("status"),
            text("reason", False),
        )
        category = request.form.get("category")
        if status not in ("pending", "approved", "rejected") or category not in {
            str(i) for i in range(10)
        }:
            abort(400)
        if status == "rejected" and not reason:
            abort(400, "拒绝时请填写原因")
        object_id, session_id, group_id = (
            text("object_id", row["source"] == "field"),
            text("session_id"),
            text("group_id"),
        )
        crop = request.form.get("crop", row["crop"])
        crop_mode = request.form.get("crop_mode", "legacy")
        if crop_mode not in ("legacy", "direct"):
            abort(400, "未知框选模式")
        if crop_mode == "direct" and not request.form.get("draw_crop"):
            crop = ""
        if crop_mode == "legacy" and request.form.get("use_crop") and not crop:
            abort(400, "请先选择裁剪区域")
        try:
            crop_box(crop, row["width"], row["height"])
        except (ValueError, TypeError):
            abort(400, "裁剪坐标无效或原图裁剪区域小于128×128")
        work.save(
            sid,
            request.form.get("lease", ""),
            request.form.get("revision", ""),
            (status, int(category), reason, object_id, session_id, group_id, crop),
            lambda: event(
                "review",
                sid,
                {
                    "status": status,
                    "decision": request.form.get("decision"),
                    "category": category,
                    "category_version": cat["category_version"],
                    "reason": reason,
                    "object_id": object_id,
                    "session_id": session_id,
                    "group_id": group_id,
                    "crop": crop,
                },
            ),
        )
        if intent == "next":
            return redirect(url_for("next_review", exclude=sid, **filters))
        flash("审核已保存。")
        return redirect(url_for("sample", sid=sid, **filters))
    row, lease, notice = work.open(sid)
    related = [
        r
        for r in db().execute("SELECT * FROM samples WHERE id<>?", (sid,))
        if (row["object_id"] and r["object_id"] == row["object_id"])
        or r["group_id"] == row["group_id"]
        or (int(r["phash"], 16) ^ int(row["phash"], 16)).bit_count() <= 6
    ]
    history = (
        db()
        .execute(
            "SELECT e.*,u.username FROM events e JOIN users u ON e.actor=u.id WHERE subject=? ORDER BY e.id DESC",
            (sid,),
        )
        .fetchall()
    )
    decision, review_note = initial_choice(row)
    automatic = ai_triage.current_decision(db(), row)
    return render_template(
        "sample.html",
        sample=row,
        lease=lease,
        notice=notice,
        filters=filters,
        automatic=automatic,
        auto_evidence=json.loads(automatic["evidence"]) if automatic else None,
        ai=ai_review.suggestion(db(), row, cat),
        decision=decision,
        decision_choices=CHOICES,
        review_note=review_note,
        source_meta=json.loads(row["source_meta"]),
        related=related[:20],
        history=history,
    )


@require()
def skip_sample(sid):
    filters = review_workflow().filters(request.args)
    review_workflow().release(sid, request.form.get("lease", ""))
    return redirect(url_for("next_review", exclude=sid, **filters))


@require()
def renew_lease(sid):
    return {"expires": review_workflow().renew(sid, request.form.get("lease", ""))}


@require()
def release_lease(sid):
    review_workflow().release(sid, request.form.get("lease", ""))
    return "", 204


def register(app):
    app.add_url_rule("/upload", view_func=upload, methods=["GET", "POST"])
    app.add_url_rule("/images/<sid>", view_func=image, methods=["GET"])
    app.add_url_rule("/samples/<sid>", view_func=sample, methods=["GET", "POST"])
    app.add_url_rule("/samples/<sid>/skip", view_func=skip_sample, methods=["POST"])
    app.add_url_rule("/samples/<sid>/lease", view_func=renew_lease, methods=["POST"])
    app.add_url_rule(
        "/samples/<sid>/release", view_func=release_lease, methods=["POST"]
    )
