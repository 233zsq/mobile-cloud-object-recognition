"""Single-image inference; the client explicitly adopts results through /records."""

import re
import time
from uuid import UUID

from flask import current_app, request

from . import api
from ..errors import ApiError
from ..inference.client import MESSAGES
from ..services.records import UUID_PATTERN


@api.post("/infer")
def infer():
    started = time.perf_counter()
    if request.mimetype != "multipart/form-data":
        raise ApiError("UNSUPPORTED_MEDIA_TYPE", "请使用 multipart/form-data 上传图片。", 415)
    if (set(request.form) != {"request_id", "model_version"} or set(request.files) != {"image"}
        or any(len(request.form.getlist(k)) != 1 for k in request.form)
        or len(request.files.getlist("image")) != 1):
        raise ApiError("INVALID_INFER_REQUEST", "须提供且仅提供 image、request_id 和 model_version。")
    request_id = request.form["request_id"]
    if not re.fullmatch(UUID_PATTERN, request_id):
        raise ApiError("INVALID_INFER_REQUEST", "request_id 必须为带连字符的 UUID。")
    if request.form["model_version"] != current_app.config["INFERENCE_MODEL_VERSION"]:
        raise ApiError("MODEL_VERSION_MISMATCH", MESSAGES["MODEL_VERSION_MISMATCH"], 409)
    client = current_app.extensions["inference_client"]
    if client is None:
        raise ApiError("MODEL_UNAVAILABLE", MESSAGES["MODEL_UNAVAILABLE"], 503)
    image = request.files["image"].stream.read(current_app.config["INFERENCE_MAX_IMAGE_BYTES"] + 1)
    if not image:
        raise ApiError("INVALID_IMAGE", MESSAGES["INVALID_IMAGE"])
    if len(image) > current_app.config["INFERENCE_MAX_IMAGE_BYTES"]:
        raise ApiError("IMAGE_TOO_LARGE", MESSAGES["IMAGE_TOO_LARGE"], 413)
    result = client.predict(image)
    response = dict(result, request_id=str(UUID(request_id)))
    response["server_ms"] = (time.perf_counter() - started) * 1000
    return response
