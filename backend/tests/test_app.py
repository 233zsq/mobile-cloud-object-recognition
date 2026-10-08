import io
import logging
from uuid import UUID

from flask import abort, request

from app.errors import ApiError


def test_health_is_honest_and_does_not_expose_config(app, client):
    app.config.update(DB_PASSWORD="private-password", API_TOKEN="private-token")
    response = client.get("/api/health?client=android")
    assert response.status_code == 200
    assert response.json == {
        "status": "ok",
        "version": "0.1.0",
        "model_loaded": False,
        "model_version": None,
        "model_status": "not_initialized",
    }
    assert "private" not in response.get_data(as_text=True)
    assert str(UUID(response.headers["X-Request-ID"])) == response.headers["X-Request-ID"]


def test_missing_route_has_json_error_and_matching_request_id(client):
    response = client.get("/api/records")
    assert response.status_code == 404
    assert response.json["error"]["code"] == "NOT_FOUND"
    assert response.json["request_id"] == response.headers["X-Request-ID"]


def test_wrong_method_retains_allow_header(client):
    response = client.post("/api/health")
    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]
    assert response.json["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unexpected_exception_does_not_expose_details(app, client):
    @app.get("/test-failure")
    def failure():
        raise RuntimeError("private-password and database connection details")

    response = client.get("/test-failure")
    assert response.status_code == 500
    assert response.json["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "private-password" not in response.get_data(as_text=True)
    assert response.json["request_id"] == response.headers["X-Request-ID"]
    assert client.get("/api/health").status_code == 200


def test_business_error(app, client):
    @app.get("/test-conflict")
    def conflict():
        raise ApiError("RECORD_CONFLICT", "记录内容冲突", 409)

    response = client.get("/test-conflict")
    assert response.status_code == 409
    assert response.json["error"] == {"code": "RECORD_CONFLICT", "message": "记录内容冲突"}


def test_http_error_preserves_retry_after(app, client):
    @app.get("/test-busy")
    def busy():
        abort(503, retry_after=2)

    response = client.get("/test-busy")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"
    assert response.json["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_body_limit_returns_json_error(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 4

    @app.post("/test-upload")
    def upload():
        request.get_data()
        return {"status": "ok"}

    response = client.post("/test-upload", data=b"12345")
    assert response.status_code == 413
    assert response.json["request_id"] == response.headers["X-Request-ID"]


def test_access_log_does_not_include_query_or_authorization(app, client, monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(app.logger, "handlers", [logging.StreamHandler(output)])
    response = client.get(
        "/api/health?token=query-secret", headers={"Authorization": "Bearer header-secret"}
    )
    logged = output.getvalue()
    assert response.headers["X-Request-ID"] in logged
    assert "query-secret" not in logged
    assert "header-secret" not in logged
