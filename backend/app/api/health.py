from flask import current_app

from . import api


@api.get("/health")
def health():
    """Service liveness only; database and model readiness are not verified."""
    return {
        "status": "ok",
        "version": current_app.config["APP_VERSION"],
        "model_loaded": False,
        "model_version": None,
        "model_status": "not_initialized",
    }
