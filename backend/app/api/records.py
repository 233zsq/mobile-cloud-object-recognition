from flask import request

from . import api
from ..errors import ApiError
from ..services.records import save_record, serialize_record, validate_upload


@api.post("/records")
def upload_record():
    if not request.is_json:
        raise ApiError("UNSUPPORTED_MEDIA_TYPE", "请使用application/json提交记录。", 415)
    payload = validate_upload(request.get_json())
    record, created = save_record(payload)
    return {"created": created, "record": serialize_record(record)}, 201 if created else 200
