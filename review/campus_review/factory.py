"""Compose review configuration, persistence, HTTP and CLI entry points."""

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from . import cli, lifecycle, routes
from .configuration import configure
from .database import initialize


def create_app(config=None):
    app = Flask("campus_review")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
    runtime = configure(app, config)
    app.extensions["review_resources"] = runtime
    app.extensions["review_data"] = runtime.data
    initialize(runtime.data)
    lifecycle.register(app)
    routes.register(app)
    cli.register(app)
    return app
