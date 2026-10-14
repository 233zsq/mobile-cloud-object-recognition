"""Resolve dependencies from the active app, never a module-level singleton."""

from flask import current_app, g
from . import ai_triage
from .database import db
from .workflow import Workflow


def resources():
    return current_app.extensions["review_resources"]


def review_workflow():
    return Workflow(
        db(),
        g.user,
        current_app.config["REVIEW_LEASE_SECONDS"],
        ai_triage.routing_context(
            resources().categories, ai_triage.configured_profiles(current_app.config)
        ),
    )
