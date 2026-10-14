"""Health endpoint for the review service."""

from ..context import resources


def health():
    return {
        "status": "ok",
        "service": "campus-review",
        "baseline": resources().baseline["model_version"],
    }


def register(app):
    app.add_url_rule("/health", view_func=health, methods=["GET"])
