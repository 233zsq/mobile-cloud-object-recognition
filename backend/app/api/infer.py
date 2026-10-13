"""Single-image inference; the client explicitly adopts results through /records."""

import re
import time
from uuid import UUID

from flask import current_app, request

from . import api
from ..errors import ApiError
from ..inference.client import MESSAGES, selected_client
from ..services.records import UUID_PATTERN
from ..inference.scope import decide, response_contract, policy_for_contract


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
    client = selected_client(current_app, request.form['model_version'])
    if client is None:
        raise ApiError("MODEL_UNAVAILABLE", MESSAGES["MODEL_UNAVAILABLE"], 503)
    image = request.files["image"].stream.read(current_app.config["INFERENCE_MAX_IMAGE_BYTES"] + 1)
    if not image:
        raise ApiError("INVALID_IMAGE", MESSAGES["INVALID_IMAGE"])
    if len(image) > current_app.config["INFERENCE_MAX_IMAGE_BYTES"]:
        raise ApiError("IMAGE_TOO_LARGE", MESSAGES["IMAGE_TOO_LARGE"], 413)
    result = client.predict(image)
    response = dict(result, request_id=str(UUID(request_id)))
    contract = response_contract(result, current_app.extensions['inference_contracts'])
    try:
        response['scope_decision'] = decide(result, contract)
    except ValueError as error:
        raise ApiError('MODEL_UNAVAILABLE', MESSAGES['MODEL_UNAVAILABLE'], 503) from error
    response['recognition_status'] = response['scope_decision']['status']
    response["server_ms"] = (time.perf_counter() - started) * 1000
    return response


@api.get('/models')
def models():
    """Expose contracts for approved models, never filesystem paths or credentials."""
    result = []
    for contract in current_app.extensions['inference_contracts']:
        available = False
        try:
            selected_client(current_app, contract['model_version']).health()
            available = True
        except ApiError:
            pass
        result.append(dict(contract, available=available, scope_policy=policy_for_contract(contract)))
    return {'default_model_version': current_app.config['INFERENCE_MODEL_VERSION'], 'models': result}
