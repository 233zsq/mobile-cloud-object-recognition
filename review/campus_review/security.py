"""Session permissions for review routes."""

from functools import wraps
from flask import abort, g, redirect, url_for


def require(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for("login"))
            if role and g.user["role"] != role:
                abort(403, "此操作需要管理员权限")
            return fn(*args, **kwargs)

        return wrapped

    return decorator
