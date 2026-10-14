"""Register grouped HTTP adapters with the existing global endpoint names."""

from . import auth, batches, candidates, photos, queue, system, triage


def register(app):
    for group in (system, auth, queue, triage, photos, batches, candidates):
        group.register(app)
