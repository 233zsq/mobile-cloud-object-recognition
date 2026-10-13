import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from app import create_app
from app.cli import DEFAULT_CATEGORIES, register_model, seed_categories
from app.config import PROJECT_ROOT
from app.extensions import db

MODEL_FILE = PROJECT_ROOT / "database/seeds/expanded-cpu-v1.metadata.json"


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DEBUG": False}, env_file=tmp_path / "missing.env")


@pytest.fixture
def client(app):
    return app.test_client()


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
