import os

import pytest

from app import create_app
from app.config import load_config


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch):
    for name in (
        "APP_DEBUG", "APP_VERSION", "LOG_LEVEL", "SERVER_HOST", "SERVER_PORT",
        "MAX_CONTENT_LENGTH", "DB_PORT", "DB_PASSWORD", "MODEL_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_dotenv_environment_and_test_override_priority(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SERVER_PORT=8081\nAPP_VERSION=file-v1\n", encoding="utf-8")
    monkeypatch.setenv("SERVER_PORT", "8082")
    app = create_app({"SERVER_PORT": 8083}, env_file=env_file)
    assert app.config["SERVER_PORT"] == 8083
    assert app.config["APP_VERSION"] == "file-v1"
    assert os.environ["SERVER_PORT"] == "8082"
    assert "APP_VERSION" not in os.environ


def test_configuration_is_reloaded_for_each_app(tmp_path, monkeypatch):
    env_file = tmp_path / "missing.env"
    monkeypatch.setenv("APP_VERSION", "one")
    first = create_app(env_file=env_file)
    monkeypatch.setenv("APP_VERSION", "two")
    second = create_app(env_file=env_file)
    assert first.config["APP_VERSION"] == "one"
    assert second.config["APP_VERSION"] == "two"


def test_defaults_and_secrets_are_not_interpolated(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DB_PASSWORD='literal-${HOME}'\n", encoding="utf-8")
    config = load_config(env_file)
    assert config["DEBUG"] is False
    assert config["SERVER_PORT"] == 8080
    assert config["DB_PASSWORD"] == "literal-${HOME}"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SERVER_PORT", "not-a-port"), ("SERVER_PORT", "0"),
        ("SERVER_PORT", "65536"), ("DB_PORT", "-1"),
        ("APP_DEBUG", "maybe"), ("LOG_LEVEL", "VERBOSE"),
        ("MAX_CONTENT_LENGTH", "0"), ("SERVER_HOST", ""),
    ],
)
def test_invalid_settings_fail_at_startup(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        create_app(env_file=tmp_path / "missing.env")
