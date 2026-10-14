"""Identifier and form validation at review entry points."""

import re
from flask import request
from werkzeug.exceptions import abort


def safe(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value or ""):
        abort(400, "名称仅限字母、数字、下划线和连字符（最多80位）")
    return value


def text(name, required=True):
    value = request.form.get(name, "").strip()
    if (required and not value) or len(value) > 160 or any(ord(c) < 32 for c in value):
        abort(400, f"{name} 必须填写，且不能超过160个字符")
    return value
