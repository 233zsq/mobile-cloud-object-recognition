"""Enforce the configured API credential even when a proxy is bypassed."""

import hmac

from flask import request

from .errors import ApiError


def register_security(app):
    @app.before_request
    def authorize_api():
        token = app.config.get("API_TOKEN", "")
        if token and request.path.startswith("/api/") and request.path != "/api/health":
            expected = ("Bearer " + token).encode("utf-8")
            if not hmac.compare_digest(request.headers.get("Authorization", "").encode("utf-8"), expected):
                raise ApiError("UNAUTHORIZED", "请提供有效访问口令。", 401)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
