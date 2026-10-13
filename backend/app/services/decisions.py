"""Optional immutable scope evidence alongside legacy eight-field records."""
import math
import re
from sqlalchemy.exc import IntegrityError
from ..errors import ApiError
from ..models import InferenceDecision

FIELDS = {'status', 'policy_version', 'policy_sha256', 'knownness', 'manual_confirmed'}


def validate_decision(value):
    def invalid():
        raise ApiError('INVALID_RECORD', '范围判断信息无效；不确定结果须先人工确认再保存。', 400)
    if not isinstance(value, dict) or set(value) - FIELDS or not {'status', 'manual_confirmed'} <= value.keys():
        invalid()
    value = {field: value.get(field) for field in FIELDS}
    if value['status'] not in ('accepted', 'uncertain', 'unavailable') or type(value['manual_confirmed']) is not bool:
        invalid()
    if value['status'] != 'accepted' and not value['manual_confirmed']:
        invalid()
    for field, pattern in [('policy_version', r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}'), ('policy_sha256', r'[a-f0-9]{64}')]:
        entry = value[field]
        if entry is None and value['status'] == 'unavailable':
            continue
        if not isinstance(entry, str) or not re.fullmatch(pattern, entry):
            invalid()
    knownness = value['knownness']
    if knownness is not None and (type(knownness) not in (int, float) or not math.isfinite(knownness) or not 0 <= knownness <= 1):
        invalid()
    return dict(value, knownness=float(knownness) if knownness is not None else None)


def serialize_decision(decision):
    return {field: getattr(decision, field) for field in FIELDS} if decision else None


def check_existing(record_id, value, session):
    if value is None:
        return  # Legacy retries cannot erase evidence attached to a newer upload.
    actual = serialize_decision(session.get(InferenceDecision, record_id))
    if actual is None:
        # Explicit evidence may arrive after a legacy POST was acknowledged late.
        # The caller has already checked all eight immutable original fields.
        try:
            with session.begin_nested():
                session.add(InferenceDecision(record_id=record_id, **value))
                session.flush()
            session.commit()
            return
        except IntegrityError:
            session.rollback()
            actual = serialize_decision(session.get(InferenceDecision, record_id))
    if actual != value:
        raise ApiError('RECORD_CONFLICT', '相同UUID已有不同范围判断信息，原记录未被修改。', 409)
