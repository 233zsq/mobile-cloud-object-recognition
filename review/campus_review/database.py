"""Schema initialization and one SQLite connection per application context."""

import json
import sqlite3
from flask import current_app, g
from . import ai_review, ai_triage
from .utils import stamp
from .workflow import SCHEMA as WORKFLOW_SCHEMA

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','reviewer')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS invites(digest TEXT PRIMARY KEY, role TEXT NOT NULL, expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY, owner INTEGER NOT NULL, filename TEXT NOT NULL,
 sha256 TEXT UNIQUE NOT NULL, category INTEGER NOT NULL, object_id TEXT NOT NULL, session_id TEXT NOT NULL,
 group_id TEXT NOT NULL, phash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
 width INTEGER NOT NULL, height INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1, batch TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, actor INTEGER NOT NULL, action TEXT NOT NULL,
 subject TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, receipt TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(version TEXT PRIMARY KEY, report TEXT NOT NULL, digest TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', decision TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, failures INTEGER NOT NULL, reset_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS egress(id INTEGER PRIMARY KEY CHECK(id=1), bytes INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO egress(id,bytes) VALUES(1,0);
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.extensions["review_data"] / "review.sqlite3",
            timeout=30,
            isolation_level=None,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def initialize(data):
    connection = sqlite3.connect(data / "review.sqlite3")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(
        SCHEMA + WORKFLOW_SCHEMA + ai_review.SCHEMA + ai_triage.SCHEMA
    )
    ai_triage.migrate(connection)
    connection.executemany(
        "INSERT OR IGNORE INTO category_assignments(category) VALUES(?)",
        [(i,) for i in range(10)],
    )
    columns = {r[1] for r in connection.execute("PRAGMA table_info(samples)")}
    for name, definition in (
        ("source", "TEXT NOT NULL DEFAULT 'field'"),
        ("source_meta", "TEXT NOT NULL DEFAULT '{}'"),
        ("crop", "TEXT NOT NULL DEFAULT ''"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE samples ADD COLUMN {name} {definition}")
    connection.commit()
    connection.close()


def append_event(connection, actor, action, subject, details):
    connection.execute(
        "INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,?,?,?,?)",
        (actor, action, subject, json.dumps(details, ensure_ascii=False), stamp()),
    )


def event(action, subject, details):
    append_event(db(), g.user["id"], action, subject, details)
