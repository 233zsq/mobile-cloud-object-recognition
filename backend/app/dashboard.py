"""Serve the small dashboard at the same origin as the API."""

from pathlib import Path

from flask import Blueprint, send_from_directory


WEB = Path(__file__).resolve().parents[2] / "web"
dashboard = Blueprint("dashboard", __name__)


@dashboard.after_request
def headers(response):
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers["Cache-Control"] = "no-cache"
    return response


@dashboard.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@dashboard.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(WEB / "assets", filename)
