from flask import current_app
from ..errors import ApiError

from . import api


@api.get("/health")
def health():
    """Keep liveness independent of database and inference worker availability."""
    client = current_app.extensions["inference_client"]
    loaded = False
    model_status = "not_initialized"
    if client is not None:
        try:
            client.health()
            loaded, model_status = True, "ready"
        except ApiError:
            model_status = "unavailable"
    return {
        "status": "ok",
        "version": current_app.config["APP_VERSION"],
        "model_loaded": loaded,
        "model_version": client.version if loaded else None,
        "model_status": model_status,
    }
