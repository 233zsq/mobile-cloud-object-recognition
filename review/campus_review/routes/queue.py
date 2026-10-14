"""HTTP adapters for queue review operations; endpoint names stay stable."""

import time
from .. import ai_review, ai_triage
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from ..context import resources, review_workflow
from ..database import db, event
from ..security import require


@require()
def index():
    cat = resources().categories
    work = review_workflow()
    filters = work.filters(request.args)
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        abort(400)
    samples, count, stats = work.listing(filters, page)
    return render_template(
        "index.html",
        samples=samples,
        stats=stats,
        filters=filters,
        **filters,
        queue_counts=work.queue_counts(filters),
        ai_audit_percent=current_app.config["REVIEW_AI_AUDIT_PERCENT"],
        ai_suggestions={
            row["id"]: ai_review.suggestion(db(), row, cat) for row in samples
        },
        ai_summary=ai_review.latest_report(db()),
        ai_pilot=ai_review.latest_report(db(), "pilot"),
        triage_summary=ai_triage.summary(
            db(),
            current_app.config["REVIEW_TRIAGE_PRIMARY_MODEL"],
            current_app.config["REVIEW_TRIAGE_POLICY"],
        ),
        ai_usage=ai_review.usage_report(ai_review.usage_totals(db())),
        ai_budget=current_app.config["REVIEW_AI_BUDGET_NANO"] / 1e9,
        ai_max_calls=current_app.config["REVIEW_AI_MAX_CALLS"],
        automatic_decisions={
            r["id"]: ai_triage.current_decision(db(), r) for r in samples
        },
        assignments=work.assignments(),
        review_now=time.time(),
        reviewers=db()
        .execute("SELECT id,username FROM users WHERE active=1 ORDER BY username")
        .fetchall(),
        page=page,
        count=count,
        egress_bytes=db().execute("SELECT bytes FROM egress WHERE id=1").fetchone()[0],
        egress_limit=current_app.config["EGRESS_LIMIT_BYTES"],
        batches=db()
        .execute("SELECT * FROM batches ORDER BY created_at DESC")
        .fetchall(),
        candidates=db()
        .execute("SELECT * FROM candidates ORDER BY created_at DESC")
        .fetchall(),
    )


@require()
def next_review():
    work = review_workflow()
    filters = work.filters(request.args)
    sid = work.next(filters, request.args.get("exclude", ""))
    if sid:
        return redirect(url_for("sample", sid=sid, **filters))
    flash("当前筛选下没有可领取的下一张照片：照片可能已审核、被占用或分配给其他成员。")
    return redirect(url_for("index", **filters))


@require("admin")
def assign_category(category):
    value = request.form.get("reviewer_id", "")
    try:
        reviewer_id = int(value) if value else None
    except ValueError:
        abort(400, "请选择有效的组员账号")
    review_workflow().assign(
        category,
        reviewer_id,
        request.form.get("revision", ""),
        lambda old: event(
            "assign_category", str(category), {"from": old, "to": reviewer_id}
        ),
    )
    flash("品类分工已保存；改派后，原审核页面须重新领取。")
    return redirect(url_for("index") + "#assignments")


def register(app):
    app.add_url_rule("/", view_func=index, methods=["GET"])
    app.add_url_rule("/review/next", view_func=next_review, methods=["GET"])
    app.add_url_rule(
        "/assignments/<int:category>", view_func=assign_category, methods=["POST"]
    )
