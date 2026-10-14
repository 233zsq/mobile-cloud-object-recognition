"""Compose all administrative and AI commands for the configured app."""


def register(app):
    from . import admin, ai_review, ai_triage
    from ..database import db

    runtime = app.extensions["review_resources"]
    admin.register(app)
    ai_review.register(app, db, runtime.data, runtime.categories)
    ai_triage.register(app, db, runtime.data, runtime.categories)
