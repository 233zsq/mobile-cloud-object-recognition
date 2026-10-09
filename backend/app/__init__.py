"""Flask application factory for the mobile-cloud recognition service."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import Flask

from .config import load_config


def create_app(
    test_config: Mapping[str, Any] | None = None,
    *,
    env_file: str | Path | None = None,
) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(load_config(env_file))
    if test_config is not None:
        app.config.from_mapping(test_config)
    app.json.ensure_ascii = False

    from .observability import configure_logging, register_request_logging
    from .errors import register_error_handlers
    from .api import api
    from .extensions import init_database
    from .cli import register_commands
    from .inference.client import init_inference

    configure_logging(app)
    register_request_logging(app)
    register_error_handlers(app)
    init_database(app)
    register_commands(app)
    init_inference(app)
    app.register_blueprint(api)
    return app
