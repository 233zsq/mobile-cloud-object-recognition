from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import json
import os
from threading import Barrier
from uuid import uuid4

import click
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from app import create_app
from app.cli import DEFAULT_CATEGORIES, register_model, render_mysql_schema, seed_categories
from app.config import PROJECT_ROOT
from app.extensions import db
from app.models import Category, InferenceRecord, ModelVersion


MODEL_FILE = PROJECT_ROOT / "database/seeds/expanded-cpu-v1.metadata.json"


@pytest.fixture(params=["sqlite", "mysql"])
def database_app(request, tmp_path):
    admin = None
    name = None
    if request.param == "mysql":
        raw_url = os.environ.get("TEST_MYSQL_ADMIN_URL")
        if not raw_url:
            pytest.skip("Set TEST_MYSQL_ADMIN_URL to test a local isolated MySQL server")
        url = make_url(raw_url)
        if url.get_backend_name() != "mysql" or url.host != "127.0.0.1" or url.database:
            pytest.fail("TEST_MYSQL_ADMIN_URL must target a local MySQL server without a database")
        name = "test_recognition_" + uuid4().hex
        admin = create_engine(url, hide_parameters=True)
        with admin.begin() as connection:
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin"))
        uri = url.set(database=name)
    else:
        uri = "sqlite:///" + (tmp_path / "records.sqlite").as_posix()
    app = create_app(
        {"TESTING": True, "DEBUG": False, "SQLALCHEMY_DATABASE_URI": uri},
        env_file=tmp_path / "missing.env",
    )
    app.config["TEST_DATABASE_KIND"] = request.param
    try:
        with app.app_context():
            if request.param == "sqlite":
                @event.listens_for(db.engine, "connect")
                def enable_foreign_keys(connection, _):
                    connection.execute("PRAGMA foreign_keys=ON")
            db.create_all()
            seed_categories(json.loads(DEFAULT_CATEGORIES.read_text(encoding="utf-8")))
            register_model(json.loads(MODEL_FILE.read_text(encoding="utf-8")))
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        if admin is not None:
            assert name.startswith("test_recognition_") and len(name) == 49
            with admin.begin() as connection:
                connection.execute(text(f"DROP DATABASE `{name}`"))
            admin.dispose()


@pytest.fixture
def upload():
    return {
        "record_id": str(uuid4()),
        "client_id": str(uuid4()),
        "inference_source": "device",
        "model_version": "expanded-cpu-v1",
        "predicted_id": 0,
        "confidence": 0.874,
        "latency_ms": 123,
        "captured_at": "2026-10-08T16:30:00.123+08:00",
    }


def count_records(app):
    with app.app_context():
        return db.session.scalar(select(func.count()).select_from(InferenceRecord))


def test_insert_and_retry_save_one_record(database_app, upload):
    client = database_app.test_client()
    first = client.post("/api/records", json=upload)
    second = client.post("/api/records", json=upload)
    assert first.status_code == 201, first.json
    assert first.json["created"] is True
    assert second.status_code == 200, second.json
    assert second.json["created"] is False
    assert first.json["record"] == second.json["record"]
    record = first.json["record"]
    assert record["captured_at"] == "2026-10-08T08:30:00.123Z"
    assert record["corrected_id"] is None and record["revision"] == 0
    assert record["category_version"] == "campus-10-v2"
    assert count_records(database_app) == 1


def test_uuid_case_and_equivalent_time_are_idempotent(database_app, upload):
    client = database_app.test_client()
    assert client.post("/api/records", json=upload).status_code == 201
    upload.update(
        record_id=upload["record_id"].upper(),
        client_id=upload["client_id"].upper(),
        captured_at="2026-10-08T08:30:00.123Z",
    )
    assert client.post("/api/records", json=upload).status_code == 200
    assert count_records(database_app) == 1


@pytest.mark.parametrize(("field", "value"), [
    ("client_id", "00000000-0000-4000-8000-000000000001"),
    ("inference_source", "cloud"), ("model_version", "unregistered-model"),
    ("predicted_id", 1), ("confidence", 0.9), ("latency_ms", 124),
    ("captured_at", "2026-10-08T16:30:01.123+08:00"),
])
def test_each_original_field_conflict_never_overwrites(database_app, upload, field, value):
    client = database_app.test_client()
    first = client.post("/api/records", json=upload)
    changed = {**upload, field: value}
    conflict = client.post("/api/records", json=changed)
    assert conflict.status_code == 409, conflict.json
    assert conflict.json["error"]["code"] == "RECORD_CONFLICT"
    retry = client.post("/api/records", json=upload)
    assert retry.status_code == 200
    assert retry.json["record"] == first.json["record"]
    assert count_records(database_app) == 1


def test_retry_retains_later_correction(database_app, upload):
    client = database_app.test_client()
    assert client.post("/api/records", json=upload).status_code == 201
    with database_app.app_context():
        record = db.session.get(InferenceRecord, upload["record_id"])
        record.corrected_id = 1
        record.corrected_at = datetime(2026, 10, 8, 9, 0, 0)
        record.revision = 1
        db.session.commit()
    retry = client.post("/api/records", json=upload)
    assert retry.status_code == 200
    assert retry.json["record"]["predicted_id"] == 0
    assert retry.json["record"]["corrected_id"] == 1
    assert retry.json["record"]["revision"] == 1


def test_cloud_source_can_be_saved(database_app, upload):
    upload["inference_source"] = "cloud"
    response = database_app.test_client().post("/api/records", json=upload)
    assert response.status_code == 201
    assert response.json["record"]["inference_source"] == "cloud"


def test_unknown_model_rejected_without_insert(database_app, upload):
    upload["model_version"] = "unknown-model"
    response = database_app.test_client().post("/api/records", json=upload)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "UNKNOWN_MODEL_VERSION"
    assert count_records(database_app) == 0


def test_idempotent_seed_and_registration_refuse_changed_versions(database_app):
    categories = json.loads(DEFAULT_CATEGORIES.read_text(encoding="utf-8"))
    model = json.loads(MODEL_FILE.read_text(encoding="utf-8"))
    with database_app.app_context():
        assert seed_categories(categories) == ("campus-10-v2", False)
        assert register_model(model) == ("expanded-cpu-v1", False)
        changed_categories = deepcopy(categories)
        changed_categories["categories"][0]["display_name"] = "不同类别"
        with pytest.raises(click.ClickException, match="拒绝覆盖"):
            seed_categories(changed_categories)
        with pytest.raises(click.ClickException, match="拒绝覆盖"):
            register_model({**model, "sha256": "0" * 64})
        assert db.session.get(ModelVersion, model["model_version"]).model_sha256 == model["sha256"]


def test_database_constraints_reject_invalid_confidence(database_app, upload):
    assert database_app.test_client().post("/api/records", json=upload).status_code == 201
    with database_app.app_context():
        record = db.session.get(InferenceRecord, upload["record_id"])
        record.confidence = 2
        with pytest.raises((IntegrityError, OperationalError)) as failure:
            db.session.commit()
        if database_app.config["TEST_DATABASE_KIND"] == "mysql":
            assert failure.value.orig.args[0] == 3819  # MySQL CHECK violation
        db.session.rollback()
        assert db.session.get(InferenceRecord, upload["record_id"]).confidence == upload["confidence"]


def test_db_init_is_safe_to_repeat_and_uses_mysql(database_app):
    if database_app.config["TEST_DATABASE_KIND"] != "mysql":
        pytest.skip("MySQL initialization command")
    runner = database_app.test_cli_runner()
    for _ in range(2):
        result = runner.invoke(args=["db-init"])
        assert result.exit_code == 0, result.output
    with database_app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Category)) == 10
        assert db.session.scalar(select(func.count()).select_from(ModelVersion)) == 1


@pytest.mark.parametrize("conflicting", [False, True])
def test_mysql_concurrent_first_uploads(database_app, upload, monkeypatch, conflicting):
    if database_app.config["TEST_DATABASE_KIND"] != "mysql":
        pytest.skip("MySQL unique-key race verification")
    barrier = Barrier(4)
    original_get = db.session.get

    def synchronized_get(entity, key, **kwargs):
        result = original_get(entity, key, **kwargs)
        if entity is InferenceRecord and key == upload["record_id"] and result is None:
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(db.session, "get", synchronized_get)

    def send(index):
        payload = dict(upload)
        if conflicting:
            payload["latency_ms"] += index
        with database_app.test_client() as client:
            response = client.post("/api/records", json=payload)
            return response.status_code, response.json

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(send, range(4)))
    statuses = [status for status, _ in results]
    assert statuses.count(201) == 1, results
    assert statuses.count(409 if conflicting else 200) == 3, results
    assert count_records(database_app) == 1


@pytest.mark.parametrize(("field", "value"), [
    ("record_id", "not-uuid"), ("client_id", None),
    ("inference_source", "automatic"), ("model_version", ""),
    ("model_version", "x" * 65), ("predicted_id", True),
    ("predicted_id", 10), ("predicted_id", 1.0),
    ("confidence", True), ("confidence", -0.1), ("confidence", float("nan")),
    ("confidence", float("inf")), ("latency_ms", -1), ("latency_ms", True),
    ("latency_ms", 2**63), ("captured_at", "2026-10-08T16:30:00"),
    ("captured_at", "2026-02-30T16:30:00+08:00"),
    ("captured_at", "2026-10-08T16:30:00.1234+08:00"),
    ("captured_at", "2026-10-08T16:30:00+08:60"),
    ("captured_at", "0001-01-01T00:00:00Z"),
])
def test_invalid_fields_do_not_access_database(client, upload, field, value):
    response = client.post("/api/records", json={**upload, field: value})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "INVALID_RECORD"


def test_missing_unknown_and_nonobject_bodies(client, upload):
    missing = dict(upload)
    missing.pop("client_id")
    for body in (missing, {**upload, "revision": 2}, [], None):
        response = client.post("/api/records", data=json.dumps(body), content_type="application/json")
        assert response.status_code == 400


def test_wrong_content_type_and_malformed_json(client):
    assert client.post("/api/records", data="text").status_code == 415
    assert client.post("/api/records", data="{", content_type="application/json").status_code == 400


def test_database_failure_returns_retryable_error_and_health_survives(app, client, upload, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("connection failed", {}, Exception("private-password"))
    monkeypatch.setattr(db.session, "get", unavailable)
    response = client.post("/api/records", json=upload)
    assert response.status_code == 503
    assert response.json["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "private-password" not in response.get_data(as_text=True)
    assert client.get("/api/health").status_code == 200


def test_initial_sql_matches_model_metadata():
    snapshot = (PROJECT_ROOT / "database/schema/001_initial.sql").read_text(encoding="utf-8")
    assert snapshot == render_mysql_schema()


def test_database_url_preserves_password_special_characters(tmp_path):
    app = create_app({"DB_PASSWORD": "literal-@:/#${HOME}"}, env_file=tmp_path / "missing.env")
    assert app.config["SQLALCHEMY_DATABASE_URI"].password == "literal-@:/#${HOME}"
