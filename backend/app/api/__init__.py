"""API route registration."""

from flask import Blueprint

api = Blueprint("api", __name__, url_prefix="/api")

from . import health, infer, records  # noqa: E402, F401
