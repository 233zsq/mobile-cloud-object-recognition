"""Authentication and single-use invitations using explicit persistence."""

import secrets
import sqlite3
import time

from werkzeug.exceptions import abort
from werkzeug.security import check_password_hash, generate_password_hash

from ..utils import sha


class BootstrapError(ValueError):
    """An administrator already exists."""


def authenticate(connection, username, password, address):
    key = sha((address + ":" + username).encode())
    attempt = connection.execute(
        "SELECT * FROM login_attempts WHERE key=?", (key,)
    ).fetchone()
    if attempt and attempt["reset_at"] > time.time() and attempt["failures"] >= 10:
        abort(429, "登录尝试过多，请15分钟后重试")
    user = connection.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username,)
    ).fetchone()
    if not user or not check_password_hash(user["password"], password):
        failures = (
            attempt["failures"] + 1
            if attempt and attempt["reset_at"] > time.time()
            else 1
        )
        connection.execute(
            "INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)",
            (key, failures, time.time() + 900),
        )
        abort(403, "账号或密码错误")
    connection.execute("DELETE FROM login_attempts WHERE key=?", (key,))
    return user


def invitation(connection, token):
    row = connection.execute(
        "SELECT * FROM invites WHERE digest=? AND consumed=0 AND expires>?",
        (sha(token.encode()), time.time()),
    ).fetchone()
    if not row:
        abort(404, "邀请无效、已使用或已过期")
    return row


def consume_invitation(connection, token, invite, username, password):
    if len(password) < 12:
        abort(400, "密码至少12个字符")
    connection.execute("BEGIN IMMEDIATE")
    try:
        changed = connection.execute(
            "UPDATE invites SET consumed=1 WHERE digest=? AND consumed=0 AND expires>?",
            (sha(token.encode()), time.time()),
        ).rowcount
        if not changed:
            abort(409, "邀请已使用")
        try:
            connection.execute(
                "INSERT INTO users(username,password,role) VALUES(?,?,?)",
                (username, generate_password_hash(password), invite["role"]),
            )
        except sqlite3.IntegrityError:
            abort(409, "账号名已使用")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def create_invitation(connection, role, lifetime):
    token = secrets.token_urlsafe(32)
    connection.execute(
        "INSERT INTO invites VALUES(?,?,?,0)",
        (sha(token.encode()), role, time.time() + lifetime),
    )
    return token


def bootstrap_invitation(connection):
    if connection.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        raise BootstrapError("Admin already exists")
    return create_invitation(connection, "admin", 86400)
