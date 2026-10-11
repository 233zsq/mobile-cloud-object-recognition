from flask import request

from . import api
from ..errors import ApiError
from ..services.records import save_record, serialize_record, validate_upload
from ..services.record_queries import correct_label, list_records


@api.post("/records")
def upload_record():
    if not request.is_json:
        raise ApiError("UNSUPPORTED_MEDIA_TYPE", "请使用application/json提交记录。", 415)
    payload = validate_upload(request.get_json())
    record, created = save_record(payload)
    return {"created": created, "record": serialize_record(record)}, 201 if created else 200


@api.patch("/records/<record_id>/label")
def update_label(record_id):
    if not request.is_json:
        raise ApiError("UNSUPPORTED_MEDIA_TYPE", "请使用application/json提交纠错。", 415)
    return correct_label(record_id, request.get_json())


@api.get("/records")
def query_records():
    return list_records(request.args)
