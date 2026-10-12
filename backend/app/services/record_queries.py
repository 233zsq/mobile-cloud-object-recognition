"""Revision-safe corrections and bounded, version-aware record reporting."""

from datetime import datetime, timezone
import re
from uuid import UUID

from flask import current_app
from sqlalchemy import case, func, select, update

from ..errors import ApiError
from ..extensions import db
from ..models import Category, InferenceRecord as Record, ModelVersion
from .records import TIME_PATTERN, UUID_PATTERN, VERSION_PATTERN, serialize_record, utc_text


def invalid(message, code="INVALID_QUERY"):
    raise ApiError(code, message, 400)


def timestamp(value, field, code="INVALID_QUERY"):
    if not isinstance(value, str) or not re.fullmatch(TIME_PATTERN, value):
        invalid(f"{field}必须为带时区的ISO-8601时间，小数最多3位。", code)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        if result.year < 1000:
            raise ValueError
        return result.replace(tzinfo=None)
    except (ValueError, OverflowError):
        invalid(f"{field}不是有效时间。", code)


def integer(value, field, minimum, maximum, code="INVALID_QUERY"):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        value = int(value)
    if type(value) is not int or not minimum <= value <= maximum:
        invalid(f"{field}必须为{minimum}至{maximum}的整数。", code)
    return value


def correct_label(record_id, body):
    code = "INVALID_CORRECTION"
    if not re.fullmatch(UUID_PATTERN, record_id):
        invalid("record_id必须为带连字符的UUID。", code)
    record_id = str(UUID(record_id))
    if not isinstance(body, dict) or set(body) != {"corrected_id", "revision", "corrected_at"}:
        invalid("纠错必须且只能包含corrected_id、revision和corrected_at。", code)
    # JSON numbers stay strict, unlike numeric query parameters.
    if type(body["corrected_id"]) is not int or type(body["revision"]) is not int:
        invalid("corrected_id和revision必须为JSON整数。", code)
    category_id = integer(body["corrected_id"], "corrected_id", 0, 9, code)
    revision = integer(body["revision"], "revision", 1, 2**63 - 1, code)
    corrected_at = timestamp(body["corrected_at"], "corrected_at", code)
    record = db.session.get(Record, record_id)
    if record is None:
        raise ApiError("RECORD_NOT_FOUND", "记录尚未上报，请先上传原记录。", 404)
    if db.session.get(Category, (record.category_version, category_id)) is None:
        raise ApiError("UNKNOWN_CATEGORY", "纠正类别不属于该记录的类别版本。", 400)
    # The comparison runs inside UPDATE, not as a read-then-write check.
    changed = db.session.execute(
        update(Record).where(Record.record_id == record_id, Record.revision < revision)
        .values(corrected_id=category_id, corrected_at=corrected_at, revision=revision),
        execution_options={"synchronize_session": False},
    ).rowcount
    if changed:
        db.session.commit()
    else:
        # End the MySQL repeatable-read snapshot before checking a competing writer.
        db.session.rollback()
    record = db.session.get(Record, record_id)
    if record is None:
        raise ApiError("RECORD_NOT_FOUND", "记录不存在。", 404)
    if not changed and (record.revision != revision or record.corrected_id != category_id
                        or record.corrected_at != corrected_at):
        raise ApiError("REVISION_CONFLICT", "服务端已有该修订号的不同内容或更新修订，原标签未被覆盖。", 409)
    return {"updated": bool(changed), "record": serialize_record(record)}


FILTERS = {"start", "end", "model_version", "category_version", "category_id",
           "category_basis", "client_id", "inference_source"}


def unique_args(args, allowed):
    if set(args) - allowed or any(len(args.getlist(key)) != 1 for key in args):
        invalid("存在未知或重复的查询参数。")
    return dict(args)


def parse_filters(args, *, pagination=False):
    values = unique_args(args, FILTERS | ({"page", "page_size"} if pagination else set()))
    conditions = []
    normalized = {}
    for field in ("start", "end"):
        if field in values:
            instant = timestamp(values[field], field)
            normalized[field] = utc_text(instant)
            conditions.append(Record.captured_at >= instant if field == "start" else Record.captured_at < instant)
    if "start" in normalized and "end" in normalized and normalized["start"] >= normalized["end"]:
        invalid("start必须早于end；end不包含在查询范围内。")
    for field in ("model_version", "category_version"):
        if field in values:
            if not re.fullmatch(VERSION_PATTERN, values[field]):
                invalid(f"{field}格式不正确。")
            if field == "model_version":
                model = db.session.get(ModelVersion, values[field])
                if model is None:
                    raise ApiError("UNKNOWN_MODEL_VERSION", "模型版本尚未登记。", 400)
                if values.get("category_version", model.category_version) != model.category_version:
                    invalid("模型与类别版本不匹配。")
            elif db.session.scalar(select(Category.id).where(Category.category_version == values[field]).limit(1)) is None:
                raise ApiError("UNKNOWN_CATEGORY_VERSION", "类别版本尚未登记。", 400)
            normalized[field] = values[field]
            conditions.append(getattr(Record, field) == values[field])
    basis = values.get("category_basis", "predicted")
    if basis not in {"predicted", "effective"}:
        invalid("category_basis必须为predicted或effective。")
    normalized["category_basis"] = basis
    if "category_id" in values:
        category_id = integer(values["category_id"], "category_id", 0, 9)
        normalized["category_id"] = category_id
        column = Record.predicted_id if basis == "predicted" else func.coalesce(Record.corrected_id, Record.predicted_id)
        conditions.append(column == category_id)
    if "client_id" in values:
        if not re.fullmatch(UUID_PATTERN, values["client_id"]):
            invalid("client_id必须为带连字符的UUID。")
        normalized["client_id"] = str(UUID(values["client_id"]))
        conditions.append(Record.client_id == normalized["client_id"])
    if "inference_source" in values:
        if values["inference_source"] not in {"device", "cloud"}:
            invalid("inference_source必须为device或cloud。")
        normalized["inference_source"] = values["inference_source"]
        conditions.append(Record.inference_source == values["inference_source"])
    page = integer(values.get("page", "0"), "page", 0, 1_000_000) if pagination else 0
    size = integer(values.get("page_size", "20"), "page_size", 1, 100) if pagination else 20
    return conditions, normalized, page, size


def list_records(args):
    conditions, filters, page, size = parse_filters(args, pagination=True)
    total = db.session.scalar(select(func.count()).select_from(Record).where(*conditions))
    records = db.session.scalars(select(Record).where(*conditions)
        .order_by(Record.captured_at.desc(), Record.record_id.asc()).offset(page * size).limit(size))
    return {"records": [serialize_record(record) for record in records], "total": total,
            "page": page, "page_size": size, "pages": (total + size - 1) // size,
            "filters": filters, "generated_at": utc_text(datetime.now(timezone.utc))}


def statistics(args):
    conditions, filters, _, _ = parse_filters(args)
    row = db.session.execute(select(
        func.count(Record.record_id), func.sum(case((Record.corrected_id.is_not(None), 1), else_=0)),
        func.sum(case((Record.confidence < ModelVersion.low_confidence_threshold, 1), else_=0)),
        func.sum(case((Record.inference_source == "device", 1), else_=0)),
        func.sum(case((Record.inference_source == "cloud", 1), else_=0)),
        func.avg(Record.latency_ms), func.min(Record.latency_ms), func.max(Record.latency_ms),
    ).select_from(Record).join(ModelVersion, Record.model_version == ModelVersion.version).where(*conditions)).one()
    counts = {}
    for name, column in (("predicted_count", Record.predicted_id), ("corrected_count", Record.corrected_id),
                         ("effective_count", func.coalesce(Record.corrected_id, Record.predicted_id))):
        for version, category_id, count in db.session.execute(select(Record.category_version, column, func.count())
                .where(*conditions, column.is_not(None)).group_by(Record.category_version, column)):
            counts.setdefault((version, category_id), {})[name] = count
    catalog = select(Category).order_by(Category.category_version, Category.id)
    category_version = filters.get("category_version")
    if "model_version" in filters:
        category_version = db.session.get(ModelVersion, filters["model_version"]).category_version
    if category_version:
        catalog = catalog.where(Category.category_version == category_version)
    categories = [{"category_version": c.category_version, "id": c.id, "label_key": c.label_key,
                   "display_name": c.display_name,
                   **{key: counts.get((c.category_version, c.id), {}).get(key, 0)
                      for key in ("predicted_count", "corrected_count", "effective_count")}}
                  for c in db.session.scalars(catalog)]
    day = func.date(Record.captured_at)
    daily = [{"date": str(date), "count": count} for date, count in db.session.execute(
        select(day, func.count()).where(*conditions).group_by(day).order_by(day))]
    models = [{"model_version": version, "count": count} for version, count in db.session.execute(
        select(Record.model_version, func.count()).where(*conditions).group_by(Record.model_version).order_by(Record.model_version))]
    return {"total_count": row[0], "corrected_count": int(row[1] or 0), "low_confidence_count": int(row[2] or 0),
            "device_count": int(row[3] or 0), "cloud_count": int(row[4] or 0),
            "latency_ms": {"average": float(row[5]) if row[5] is not None else None, "min": row[6], "max": row[7]},
            "categories": categories, "daily_counts": daily, "models": models, "filters": filters,
            "generated_at": utc_text(datetime.now(timezone.utc)), "timezone": "UTC"}


def categories(args):
    values = unique_args(args, {"model_version", "category_version"})
    # Reuse filter checks so invalid and inconsistent versions have identical errors.
    parse_filters(args)
    models = list(db.session.scalars(select(ModelVersion).order_by(ModelVersion.registered_at.desc(), ModelVersion.version)))
    active = values.get("model_version", current_app.config["INFERENCE_MODEL_VERSION"])
    model = next((m for m in models if m.version == active), models[0] if models else None)
    version = values.get("category_version", model.category_version if model else None)
    catalogs = {}
    for c in db.session.scalars(select(Category).order_by(Category.category_version, Category.id)):
        catalogs.setdefault(c.category_version, []).append({"id": c.id, "label_key": c.label_key,
                                                          "display_name": c.display_name, "definition": c.definition})
    if version is None and catalogs:
        version = sorted(catalogs)[-1]
    return {"category_version": version, "categories": catalogs.get(version, []), "catalogs": catalogs,
            "models": [{"model_version": m.version, "category_version": m.category_version,
                        "low_confidence_threshold": m.low_confidence_threshold} for m in models]}
