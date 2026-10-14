"""Compatibility with deployed entry points and independent app resources."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import click
import pytest
from werkzeug.exceptions import Conflict

from campus_review import ROOT, create_app
from campus_review.context import resources
from campus_review.database import db
from campus_review.services.batches import freeze_batch
from campus_review.services.photos import store_photo
from review_support import photo


def parameter_type(value):
    if isinstance(value, click.Path):
        return {
            "name": "path",
            "type": value.type.__name__ if value.type else None,
            **{
                name: getattr(value, name)
                for name in (
                    "exists",
                    "file_okay",
                    "dir_okay",
                    "readable",
                    "writable",
                    "executable",
                    "resolve_path",
                    "allow_dash",
                )
            },
        }
    return str(value)


def test_routes_cli_and_sqlite_schema_match_pre_refactor_contract(app):
    expected = json.loads(
        (Path(__file__).parent / "fixtures/review-contract.json").read_text(
            encoding="utf-8"
        )
    )
    routes = sorted(
        [
            {
                "path": rule.rule,
                "endpoint": rule.endpoint,
                "methods": sorted(rule.methods),
            }
            for rule in app.url_map.iter_rules()
        ],
        key=lambda rule: (rule["path"], rule["endpoint"]),
    )
    commands = {
        name: [
            {
                "name": param.name,
                "opts": param.opts,
                "secondary_opts": param.secondary_opts,
                "required": param.required,
                "default": param.default,
                "type": parameter_type(param.type),
                "nargs": param.nargs,
            }
            for param in command.params
        ]
        for name, command in sorted(app.cli.commands.items())
    }
    with sqlite3.connect(Path(app.config["DATA_DIR"]) / "review.sqlite3") as connection:
        schema = [
            list(row)
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
            )
        ]
    actual = json.loads(
        json.dumps({"routes": routes, "cli": commands, "schema": schema}, default=str)
    )
    assert actual == expected


def test_app_resources_connections_and_cli_invitations_are_isolated(app, tmp_path):
    other = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "other-" * 10,
            "DATA_DIR": str(tmp_path / "other"),
            "SESSION_COOKIE_SECURE": False,
            "CATEGORIES_FILE": ROOT.parent
            / "shared/category-versions/campus-10-v3.json",
        }
    )
    first_invite = app.test_cli_runner().invoke(args=["bootstrap"])
    second_invite = other.test_cli_runner().invoke(args=["bootstrap"])
    assert first_invite.exit_code == second_invite.exit_code == 0
    first_path, second_path = first_invite.output.strip(), second_invite.output.strip()
    assert app.test_client().get(first_path).status_code == 200
    assert other.test_client().get(second_path).status_code == 200
    assert app.test_client().get(second_path).status_code == 404
    assert other.test_client().get(first_path).status_code == 404
    with app.app_context():
        first_connection = db()
        assert resources().categories["category_version"] == "campus-10-v4"
        with other.app_context():
            assert db() is not first_connection
            assert resources().categories["category_version"] == "campus-10-v3"
        assert db() is first_connection
    with pytest.raises(sqlite3.ProgrammingError):
        first_connection.execute("SELECT 1")


def test_photo_and_batch_services_work_without_flask_context_and_rollback_failure(app):
    runtime = app.extensions["review_resources"]
    content = photo().getvalue()
    with sqlite3.connect(
        runtime.data / "review.sqlite3", isolation_level=None
    ) as connection:
        connection.row_factory = sqlite3.Row
        owner = connection.execute(
            "INSERT INTO users(username,password,role) VALUES('service-test','unused','admin')"
        ).lastrowid
        sid = store_photo(
            connection, runtime.data, content, 0, "cup-1", "session-1", "group-1", owner
        )
        connection.execute(
            "UPDATE samples SET status='approved',revision=2 WHERE id=?", (sid,)
        )
        row = connection.execute("SELECT * FROM samples WHERE id=?", (sid,)).fetchone()
        original = runtime.data / "images" / row["filename"]
        original.write_bytes(b"changed")
        with pytest.raises(Conflict):
            freeze_batch(
                connection,
                runtime.data,
                runtime.categories,
                runtime.category_bytes,
                owner,
                "failed",
            )
        assert not connection.in_transaction
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
        assert not (runtime.data / "batches/failed.zip").exists()
        original.write_bytes(content)
        receipt = freeze_batch(
            connection,
            runtime.data,
            runtime.categories,
            runtime.category_bytes,
            owner,
            "service-batch",
        )
        assert receipt["purpose"] == "training_only" and receipt["count"] == 1
        with zipfile.ZipFile(runtime.data / "batches/service-batch.zip") as archive:
            assert archive.read("images/" + row["filename"]) == content
            assert (
                json.loads(archive.read("batch.json"))["categories_sha256"]
                == app.config["REVIEW_AI_CATEGORY_SHA256"]
            )
        assert connection.execute(
            "SELECT batch,revision FROM samples WHERE id=?", (sid,)
        ).fetchone()[:] == ("service-batch", 3)


def test_importing_review_modules_does_not_start_work_or_create_data():
    code = """
import pathlib, sqlite3, subprocess, sys, threading, urllib.request
sys.path.insert(0, str(pathlib.Path.cwd() / 'review'))
def forbidden(*args, **kwargs):
    raise AssertionError('Import started work')
pathlib.Path.mkdir = pathlib.Path.write_text = pathlib.Path.write_bytes = forbidden
sqlite3.connect = subprocess.Popen = threading.Thread.start = urllib.request.urlopen = forbidden
import campus_review
import importlib, pkgutil
for module in pkgutil.walk_packages(campus_review.__path__, campus_review.__name__ + '.'):
    importlib.import_module(module.name)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT.parent,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
