"""Gunicorn entry point: gunicorn --workers 1 --bind 127.0.0.1:8080 wsgi:app."""

from app import create_app

app = create_app()
