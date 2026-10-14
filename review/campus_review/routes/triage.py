"""HTTP adapters for triage review operations; endpoint names stay stable."""

from .. import ai_triage
from flask import abort, current_app, flash, g, redirect, request, url_for
from ..database import db
from ..security import require


@require("admin")
def triage_policy():
    value = request.form.get("enabled")
    if value not in ("true", "false"):
        abort(400, "请选择开启或暂停")
    ai_triage.set_enabled(
        db(),
        g.user["id"],
        value == "true",
        ai_triage.policy_for(ai_triage.configured_profiles(current_app.config)),
    )
    flash(
        "自动审核已开启。"
        if value == "true"
        else "自动审核已暂停；进行中的调用结束后停止写入。"
    )
    return redirect(url_for("index") + "#ai-triage")


@require("admin")
def triage_job():
    try:
        limit = int(request.form.get("limit", "20"))
    except ValueError:
        abort(400, "请输入1到50之间的整数")
    identity = ai_triage.new_job(db(), g.user["id"], limit, current_app.config)
    try:
        pid = ai_triage.launch(current_app._get_current_object(), identity)
        db().execute(
            'UPDATE ai_triage_jobs SET pid=? WHERE id=? AND state="queued"',
            (pid, identity),
        )
    except OSError:
        db().execute(
            'UPDATE ai_triage_jobs SET state="interrupted",error_code="launch_failed" WHERE id=? AND state="queued"',
            (identity,),
        )
        abort(409, "任务未能启动，请联系管理员检查服务")
    flash("分流任务已启动，刷新可查看进度。")
    return redirect(url_for("index") + "#ai-triage")


@require("admin")
def undo_automatic(sid):
    ai_triage.undo(db(), g.user["id"], sid, request.form.get("revision", ""))
    flash("AI决定已撤回，照片回到人工待审核队列。")
    return redirect(url_for("index", status="pending"))


def register(app):
    app.add_url_rule("/ai-triage/policy", view_func=triage_policy, methods=["POST"])
    app.add_url_rule("/ai-triage/jobs", view_func=triage_job, methods=["POST"])
    app.add_url_rule(
        "/samples/<sid>/ai-undo", view_func=undo_automatic, methods=["POST"]
    )
