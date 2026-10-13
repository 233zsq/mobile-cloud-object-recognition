from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, local
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.cli import register_model, seed_categories
from app.config import PROJECT_ROOT
from app.extensions import db
from app.models import Category, InferenceRecord


def correction(revision=1, category=1):
    return {"corrected_id": category, "revision": revision, "corrected_at": "2026-10-09T10:00:00.123+08:00"}


def test_correction_retries_conflicts_and_immutable_upload(database_app, upload):
    client = database_app.test_client()
    assert client.post("/api/records", json=upload).status_code == 201
    path = f'/api/records/{upload["record_id"].upper()}/label'
    first = client.patch(path, json=correction())
    assert first.status_code == 200 and first.json["updated"] is True
    assert first.json["record"]["predicted_id"] == 0
    assert first.json["record"]["corrected_at"] == "2026-10-09T02:00:00.123Z"
    retry = client.patch(path, json={**correction(), "corrected_at": "2026-10-09T02:00:00.123Z"})
    assert retry.status_code == 200 and retry.json["updated"] is False
    assert client.patch(path, json=correction(category=2)).status_code == 409
    assert client.patch(path, json={**correction(), "corrected_at": "2026-10-09T02:00:00.124Z"}).status_code == 409
    assert client.patch(path, json=correction(5, 2)).status_code == 200  # Offline intermediate revisions may be skipped.
    assert client.patch(path, json=correction(3, 3)).status_code == 409
    retry_upload = client.post("/api/records", json=upload)
    assert retry_upload.status_code == 200
    assert retry_upload.json["record"]["corrected_id"] == 2
    assert retry_upload.json["record"]["revision"] == 5
    assert client.post("/api/records", json={**upload, "predicted_id": 2}).status_code == 409


@pytest.mark.parametrize("body", [None, [], {}, {**correction(), "extra": 1}, correction(0),
    correction(-1), correction(2**63), correction(True), correction("1"), correction(category=True),
    correction(category=1.0), correction(category=10), {**correction(), "corrected_at": "2026-02-30T00:00:00Z"},
    {**correction(), "corrected_at": "2026-10-09T00:00:00.1234Z"}])
def test_bad_corrections_are_rejected_without_database_access(client, body):
    response = client.patch(f"/api/records/{uuid4()}/label", data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert response.json["error"]["code"] == "INVALID_CORRECTION"


def test_correction_missing_record_and_category_version(database_app, upload):
    client = database_app.test_client()
    path = f'/api/records/{upload["record_id"]}/label'
    assert client.patch(path, json=correction()).status_code == 404
    assert client.patch("/api/records/bad/label", json=correction()).status_code == 400
    assert client.patch(path, data="text").status_code == 415
    assert client.patch(path, data="{", content_type="application/json").status_code == 400
    assert client.post("/api/records", json=upload).status_code == 201
    with database_app.app_context():
        seed_categories(json.loads((PROJECT_ROOT / "shared/category-versions/campus-10-v4.json").read_text(encoding="utf-8")))
        db.session.execute(delete(Category).where(Category.category_version == "campus-10-v2", Category.id == 9))
        db.session.commit()
    response = client.patch(path, json=correction(category=9))
    assert response.status_code == 400 and response.json["error"]["code"] == "UNKNOWN_CATEGORY"


@pytest.mark.parametrize("mode", ["increasing", "same", "conflicting"])
def test_mysql_concurrent_corrections_keep_latest_revision(database_app, upload, monkeypatch, mode):
    if database_app.config["TEST_DATABASE_KIND"] != "mysql":
        pytest.skip("Atomic MySQL revision race")
    assert database_app.test_client().post("/api/records", json=upload).status_code == 201
    barrier, seen = Barrier(4), local()
    get = db.session.get

    def synchronized_get(entity, key, **kwargs):
        result = get(entity, key, **kwargs)
        if entity is InferenceRecord and not getattr(seen, "initial_read", False):
            seen.initial_read = True
            barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(db.session, "get", synchronized_get)

    def send(index):
        revision = index + 1 if mode == "increasing" else 1
        category = 1 if mode == "same" else index + 1
        with database_app.test_client() as client:
            response = client.patch(f'/api/records/{upload["record_id"]}/label', json=correction(revision, category))
            return response.status_code, response.json

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(send, range(4)))
    if mode == "same":
        assert [s for s, _ in results] == [200] * 4
        assert sum(r["updated"] for _, r in results) == 1
    elif mode == "conflicting":
        assert sorted(s for s, _ in results) == [200, 409, 409, 409]
    else:
        assert results[3][0] == 200
        assert all(s in (200, 409) for s, _ in results)
    with database_app.app_context():
        record = db.session.scalars(select(InferenceRecord)).one()
        assert record.revision == (4 if mode == "increasing" else 1)
        if mode == "increasing":
            assert record.corrected_id == 4
        assert record.predicted_id == 0


@pytest.fixture
def populated(database_app, upload):
    with database_app.app_context():
        seed_categories(json.loads((PROJECT_ROOT / "shared/category-versions/campus-10-v4.json").read_text(encoding="utf-8")))
        metadata = json.loads((PROJECT_ROOT / "models/releases/campus-evolve-v2/metadata.json").read_text(encoding="utf-8"))
        metadata["low_confidence_threshold"] = 0.9  # Distinct thresholds expose incorrect global-threshold aggregation.
        register_model(metadata)
    client = database_app.test_client()
    entries = []
    for index, (day, model, category, confidence, source) in enumerate([
        (8, "expanded-cpu-v1", 0, 0.5, "device"), (9, "expanded-cpu-v1", 1, 0.49, "device"),
        (9, "campus-evolve-v2", 5, 0.8, "cloud"), (10, "campus-evolve-v2", 5, 0.9, "cloud"),
    ]):
        body = {**upload, "record_id": str(uuid4()), "captured_at": f"2026-10-{day:02}T08:00:00.000Z",
                "model_version": model, "predicted_id": category, "confidence": confidence,
                "inference_source": source, "latency_ms": 100 * (index + 1)}
        assert client.post("/api/records", json=body).status_code == 201
        entries.append(body)
    assert client.patch(f'/api/records/{entries[0]["record_id"]}/label', json=correction()).status_code == 200
    return database_app, entries


def test_reporting_counts_thresholds_and_versioned_labels(populated):
    app, entries = populated
    client = app.test_client()
    stats = client.get("/api/stats").json
    assert (stats["total_count"], stats["corrected_count"], stats["low_confidence_count"]) == (4, 1, 2)
    assert stats["device_count"] == stats["cloud_count"] == 2
    assert stats["latency_ms"] == {"average": 250, "min": 100, "max": 400}
    counts = {(c["category_version"], c["id"]): c for c in stats["categories"]}
    assert counts[("campus-10-v2", 0)]["predicted_count"] == 1
    assert counts[("campus-10-v2", 0)]["effective_count"] == 0
    assert counts[("campus-10-v2", 1)]["corrected_count"] == 1
    assert counts[("campus-10-v2", 1)]["effective_count"] == 2
    assert counts[("campus-10-v4", 5)]["display_name"] == "键盘"
    assert counts[("campus-10-v4", 5)]["predicted_count"] == 2
    assert sum(c["effective_count"] for c in stats["categories"]) == 4
    assert stats["daily_counts"] == [{"date": "2026-10-08", "count": 1}, {"date": "2026-10-09", "count": 2}, {"date": "2026-10-10", "count": 1}]
    assert sum(m["count"] for m in stats["models"]) == 4
    app.config["INFERENCE_MODEL_VERSION"] = "campus-evolve-v2"
    catalog = client.get("/api/categories").json
    assert catalog["category_version"] == "campus-10-v4"
    assert len(catalog["categories"]) == 10 and len(catalog["models"]) == 2
    assert client.get("/api/categories?model_version=expanded-cpu-v1").json["category_version"] == "campus-10-v2"


def test_filters_pagination_and_half_open_time_ranges(populated):
    app, entries = populated
    client = app.test_client()
    first = client.get("/api/records?page=0&page_size=2").json
    second = client.get("/api/records?page=1&page_size=2").json
    assert first["total"] == 4 and first["pages"] == 2
    assert first["records"][0]["record_id"] == entries[3]["record_id"]
    assert not ({r["record_id"] for r in first["records"]} & {r["record_id"] for r in second["records"]})
    assert client.get("/api/records?page=3").json["records"] == []
    query = "start=2026-10-09T16:00:00.000%2B08:00&end=2026-10-10T08:00:00Z"
    assert client.get("/api/records?" + query).json["total"] == 2
    assert client.get("/api/stats?" + query).json["total_count"] == 2
    assert client.get("/api/records?model_version=campus-evolve-v2&category_id=5").json["total"] == 2
    assert client.get("/api/stats?category_id=1&category_basis=effective").json["total_count"] == 2
    assert client.get("/api/stats?category_id=1").json["total_count"] == 1
    assert client.get("/api/records?inference_source=cloud").json["total"] == 2
    assert client.get(f'/api/records?client_id={entries[0]["client_id"].upper()}').json["total"] == 4
    assert client.get(f'/api/records?client_id={uuid4()}').json["total"] == 0


@pytest.mark.parametrize("query", ["page=-1", "page_size=0", "page_size=101", "page=1.0", "page=true",
    "start=2026-10-12", "start=2026-10-10T00:00:00Z&end=2026-10-09T00:00:00Z",
    "page=0&page=1", "extra=1", "category_id=10", "category_basis=unknown", "inference_source=other"])
def test_invalid_query(client, query):
    assert client.get("/api/records?" + query).status_code == 400


def test_empty_results_and_invalid_versions(database_app):
    client = database_app.test_client()
    stats = client.get("/api/stats").json
    assert stats["total_count"] == stats["low_confidence_count"] == stats["corrected_count"] == 0
    assert stats["latency_ms"] == {"average": None, "min": None, "max": None}
    assert stats["daily_counts"] == []
    assert client.get("/api/records").json["pages"] == 0
    for path in ("records", "stats", "categories"):
        assert client.get(f"/api/{path}?model_version=missing").status_code == 400
        assert client.get(f"/api/{path}?category_version=missing").status_code == 400
        assert client.get(f"/api/{path}?model_version=expanded-cpu-v1&category_version=campus-10-v4").status_code == 400


@pytest.mark.parametrize("path", ["/api/records", "/api/stats", "/api/categories"])
def test_read_failure_keeps_health_available(app, client, monkeypatch, path):
    def unavailable(*args, **kwargs):
        raise OperationalError("connection failed", {}, Exception("private-password"))
    monkeypatch.setattr(db.session, "execute", unavailable)
    response = client.get(path)
    assert response.status_code == 503
    assert "private-password" not in response.get_data(as_text=True)
    assert client.get("/api/health").status_code == 200


def test_authentication_and_static_dashboard(app, client):
    app.config["API_TOKEN"] = "test-secret"
    for path in ("/api/records", "/api/stats", "/api/categories", "/api/infer"):
        response = client.get(path)
        assert response.status_code == 401 and response.json["error"]["code"] == "UNAUTHORIZED"
        assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    assert "test-secret" not in client.get("/").get_data(as_text=True)
    assert "frame-ancestors 'none'" in client.get("/").headers["Content-Security-Policy"]
    assert client.get("/assets/js/dashboard.js").status_code == 200
    assert 'type="module"' in client.get('/').get_data(as_text=True)
    for module in ('controller', 'api', 'filters', 'state', 'view'):
        response = client.get('/assets/js/dashboard/' + module + '.js')
        assert response.status_code == 200
        assert response.mimetype in ('text/javascript', 'application/javascript', 'application/x-javascript')
    assert client.get("/assets/css/dashboard.css").status_code == 200
    assert client.get("/assets/../../.env").status_code == 404
    assert client.get("/api/stats", headers={"Authorization": "Bearer TEST-SECRET"}).status_code == 401
    # With a correct token, the unavailable DB is reported instead of bypassing authorization.
    assert client.get("/api/stats", headers={"Authorization": "Bearer test-secret"}).status_code == 503
