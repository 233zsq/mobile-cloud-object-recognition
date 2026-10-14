"""Request context, CSRF, error responses and transaction cleanup."""

import secrets
from flask import abort, g, render_template, request, session
from werkzeug.exceptions import SecurityError
from .context import resources
from .database import db


def register(app):
    @app.before_request
    def context():
        g.app_data = resources().data
        g.user = (
            db()
            .execute(
                "SELECT * FROM users WHERE id=? AND active=1", (session.get("uid", -1),)
            )
            .fetchone()
        )
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.method == "POST" and not secrets.compare_digest(
            session["csrf"], request.form.get("csrf", "")
        ):
            abort(400, "页面校验失败，请刷新后重试")

    @app.teardown_appcontext
    def close(_error):
        if conn := g.pop("db", None):
            conn.close()

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.endpoint == "image" and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "private, no-cache"
            response.vary.add("Cookie")
        else:
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.context_processor
    def globals_():
        runtime = resources()
        return {
            "categories": runtime.categories["categories"],
            "csrf": session.get("csrf"),
            "baseline": runtime.baseline,
            "base_metrics": runtime.base_metrics,
            "source_labels": {
                "field": "成员实拍",
                "wikimedia_commons": "Commons 网图",
                "open_images": "Open Images 网图",
                "web_product": "商品网图（授权未核实）",
            },
        }

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def error(exc):
        if isinstance(exc, SecurityError):
            return "Untrusted host", 400, {"Content-Type": "text/plain; charset=utf-8"}
        if db().in_transaction:
            db().rollback()
        return render_template(
            "error.html", message=exc.description, code=exc.code
        ), exc.code

    @app.teardown_request
    def rollback(_exc):
        if "db" in g and g.db.in_transaction:
            g.db.rollback()
