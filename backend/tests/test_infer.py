import io
from uuid import uuid4

import pytest
from werkzeug.datastructures import MultiDict

from app.errors import ApiError
from app.inference.client import ModelClient


class ReadyModel:
    version = "campus-gpu-v1"
    def __init__(self):
        self.images = []
    def health(self):
        return {"model_loaded": True}
    def predict(self, image):
        self.images.append(image)
        return {"model_version":self.version,"model_sha256":"a"*64,
                "predicted_id":0,"label_key":"cup","confidence":0.9,"low_confidence":False,
                "scores":[0.9]+[0.1/9]*9,"preprocess_ms":1.0,"inference_ms":2.0,"model_call_ms":3.0}


def fields(**changes):
    return dict({"request_id":str(uuid4()),"model_version":"campus-gpu-v1",
                 "image":(io.BytesIO(b"image-bytes"),"photo.jpg")},**changes)


def test_infer_echoes_client_uuid_without_persisting_a_record(app, client, monkeypatch):
    import app.services.records as records
    monkeypatch.setattr(records,"save_record",lambda _:pytest.fail("Inference must not save records"))
    model = ReadyModel()
    app.extensions["inference_client"] = model
    form = fields()
    response = client.post("/api/infer",data=form)
    assert response.status_code == 200
    assert response.json["request_id"] == form["request_id"]
    assert response.json["model_version"] == "campus-gpu-v1"
    assert response.json["server_ms"] >= 0
    assert model.images == [b"image-bytes"]
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("change,expected",[
    ({"request_id":"not-a-uuid"},"INVALID_INFER_REQUEST"),
    ({"extra":"unexpected"},"INVALID_INFER_REQUEST"),
    ({"model_version":"expanded-cpu-v1"},"MODEL_VERSION_MISMATCH"),
])
def test_invalid_form_never_calls_runtime(app,client,change,expected):
    model = ReadyModel()
    app.extensions["inference_client"] = model
    response = client.post("/api/infer",data=fields(**change))
    assert response.status_code in (400,409)
    assert response.json["error"]["code"] == expected
    assert not model.images


def test_rejects_duplicate_multipart_fields(app,client):
    app.extensions["inference_client"] = ReadyModel()
    form=MultiDict(fields())
    form.add("model_version","expanded-cpu-v1")
    response=client.post("/api/infer",data=form)
    assert response.status_code==400
    assert not app.extensions["inference_client"].images


def test_file_limit_is_applied_before_runtime(app,client):
    app.extensions["inference_client"] = ReadyModel()
    app.config["INFERENCE_MAX_IMAGE_BYTES"] = 4
    response=client.post("/api/infer",data=fields())
    assert response.status_code==413
    assert response.json["error"]["code"]=="IMAGE_TOO_LARGE"
    assert not app.extensions["inference_client"].images


def test_unconfigured_model_and_wrong_content_type(client):
    assert client.post("/api/infer",data=fields()).status_code==503
    response=client.post("/api/infer",json={})
    assert response.status_code==415


def test_failed_worker_does_not_fail_liveness(app,client):
    model=ReadyModel()
    def fail():
        raise ApiError("MODEL_UNAVAILABLE","unavailable",503)
    model.health=fail
    app.extensions["inference_client"]=model
    response=client.get("/api/health")
    assert response.status_code==200
    assert response.json["model_loaded"] is False
    assert response.json["model_status"]=="unavailable"
    model.health=lambda:{"model_loaded":True}
    assert client.get("/api/health").json["model_version"]=="campus-gpu-v1"


@pytest.mark.parametrize("scores,predicted",[
    ([float("nan")]+[0.0]*9,0),([0.1]*10,11),([1.0]+[0.0]*8,0),
])
def test_invalid_runtime_scores_are_sanitized(monkeypatch,scores,predicted):
    model=ModelClient("unused","campus-gpu-v1","a"*64)
    result=ReadyModel().predict(b"data")
    result.update(scores=scores,predicted_id=predicted)
    monkeypatch.setattr(model,"_request",lambda *a,**k:result)
    with pytest.raises(ApiError) as error:
        model.predict(b"data")
    assert error.value.code=="MODEL_UNAVAILABLE"
