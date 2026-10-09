"""Validate immutable uploads and save exactly one row per UUID."""

from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from ..errors import ApiError
from ..extensions import db
from ..models import Category, InferenceRecord, ModelVersion


FIELDS = {
    "record_id", "client_id", "inference_source", "model_version",
    "predicted_id", "confidence", "latency_ms", "captured_at",
}
VERSION_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
TIME_PATTERN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)"


def invalid(message):
    raise ApiError("INVALID_RECORD", message, 400)


def utc_text(value):
    return value.replace(tzinfo=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_upload(body):
    if not isinstance(body, dict):
        invalid("请求体必须为JSON对象。")
    missing = FIELDS - body.keys()
    unknown = body.keys() - FIELDS
    if missing:
        invalid("缺少字段：" + ", ".join(sorted(missing)))
    if unknown:
        invalid("不支持的字段：" + ", ".join(sorted(unknown)))
    payload = dict(body)
    for field in ("record_id", "client_id"):
        value = payload[field]
        if not isinstance(value, str) or not re.fullmatch(UUID_PATTERN, value):
            invalid(f"{field}必须为带连字符的UUID。")
        payload[field] = str(UUID(value))
    if payload["inference_source"] not in ("device", "cloud"):
        invalid("inference_source必须为device或cloud。")
    if not isinstance(payload["model_version"], str) or not re.fullmatch(VERSION_PATTERN, payload["model_version"]):
        invalid("model_version必须为1至64位字母、数字、点、下划线或连字符，以字母或数字开头。")
    predicted = payload["predicted_id"]
    if type(predicted) is not int or not 0 <= predicted <= 9:
        invalid("predicted_id必须为0至9的整数。")
    confidence = payload["confidence"]
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
        invalid("confidence必须为0至1的有限数值。")
    payload["confidence"] = float(confidence) or 0.0
    latency = payload["latency_ms"]
    if type(latency) is not int or not 0 <= latency <= 2**63 - 1:
        invalid("latency_ms必须为非负64位整数。")
    value = payload["captured_at"]
    if not isinstance(value, str) or not re.fullmatch(TIME_PATTERN, value):
        invalid("captured_at必须为带时区的ISO-8601时间，小数精度最多3位。")
    try:
        captured = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        invalid("captured_at不是有效时间。")
    if captured.year < 1000:
        invalid("captured_at超出MySQL DATETIME范围。")
    payload["captured_at"] = utc_text(captured.replace(tzinfo=None))
    return payload


def fingerprint(payload):
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def existing_result(record, payload):
    # Check the actual immutable fields as well as their stored digest.
    original = {field: getattr(record, field) for field in FIELDS}
    original["captured_at"] = utc_text(record.captured_at)
    if original != payload or record.payload_sha256 != fingerprint(payload):
        raise ApiError("RECORD_CONFLICT", "相同UUID已存在不同内容，原记录未被修改。", 409)
    return record, False


def save_record(payload):
    existing = db.session.get(InferenceRecord, payload["record_id"])
    if existing is not None:
        return existing_result(existing, payload)

    model = db.session.get(ModelVersion, payload["model_version"])
    if model is None:
        raise ApiError("UNKNOWN_MODEL_VERSION", "模型版本尚未登记。", 400)
    category = db.session.get(Category, (model.category_version, payload["predicted_id"]))
    if category is None:
        raise ApiError("UNKNOWN_CATEGORY", "该类别不属于模型的类别版本。", 400)

    values = dict(payload)
    values["captured_at"] = datetime.fromisoformat(payload["captured_at"].replace("Z", "+00:00")).replace(tzinfo=None)
    record = InferenceRecord(
        **values,
        category_version=model.category_version,
        payload_sha256=fingerprint(payload),
    )
    db.session.add(record)
    try:
        db.session.commit()
    except IntegrityError:
        # A competing request may have committed the same UUID after our lookup.
        db.session.rollback()
        winner = db.session.get(InferenceRecord, payload["record_id"])
        if winner is None:
            raise
        return existing_result(winner, payload)
    return record, True


def serialize_record(record):
    result = {field: getattr(record, field) for field in FIELDS}
    result.update(
        captured_at=utc_text(record.captured_at),
        category_version=record.category_version,
        corrected_id=record.corrected_id,
        corrected_at=utc_text(record.corrected_at) if record.corrected_at else None,
        revision=record.revision,
        created_at=utc_text(record.created_at),
    )
    return result
