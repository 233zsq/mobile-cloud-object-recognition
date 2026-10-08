"""Console logs and server-generated request IDs."""

import logging
import sys
import time
from uuid import uuid4

from flask import Flask, g, request


def configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(app.config["LOG_LEVEL"])
    app.logger.propagate = False


def register_request_logging(app: Flask) -> None:
    @app.before_request
    def start_request() -> None:
        g.request_id = str(uuid4())
        g.request_started = time.perf_counter()

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = g.request_id
        elapsed_ms = (time.perf_counter() - g.request_started) * 1000
        app.logger.info(
            "request_id=%s method=%s path=%r status=%s elapsed_ms=%.2f",
            g.request_id,
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
        )
        return response
