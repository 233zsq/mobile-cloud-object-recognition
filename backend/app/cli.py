"""Explicit schema initialization and immutable category/model registration."""

import json
from pathlib import Path
import re

import click
from sqlalchemy import select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateIndex, CreateTable

from .config import PROJECT_ROOT
from .extensions import db
from .models import Category, ModelVersion
from .services.records import VERSION_PATTERN


DEFAULT_CATEGORIES = PROJECT_ROOT / "database/seeds/categories.campus-10-v2.json"


def render_mysql_schema():
    lines = [
        "-- Initial schema 001; generated from backend/app/models/__init__.py.",
        "-- MySQL 8.0.16+; run inside the selected empty application database.",
        "-- Future structure changes require a new versioned migration.",
        "SET NAMES utf8mb4;",
        "SET time_zone = '+00:00';",
    ]
    dialect = mysql.dialect()
    for table in db.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda item: item.name):
            lines.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    return "\n".join(line.rstrip() for line in "\n\n".join(lines).splitlines()) + "\n"


def read_object(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise click.ClickException("无法读取有效JSON文件。") from exc
    if not isinstance(value, dict):
        raise click.ClickException("文件必须包含JSON对象。")
    return value


def version(value):
    if not isinstance(value, str) or not re.fullmatch(VERSION_PATTERN, value):
        raise click.ClickException("版本名须为1至64位字母、数字、点、下划线或连字符，以字母或数字开头。")
    return value


def seed_categories(data):
    category_version = version(data.get("category_version"))
    categories = data.get("categories")
    if data.get("status") != "frozen" or not isinstance(categories, list) or len(categories) != 10:
        raise click.ClickException("须提供已冻结的10类清单。")
    rows = []
    for entry in categories:
        if not isinstance(entry, dict) or type(entry.get("id")) is not int:
            raise click.ClickException("类别ID必须为整数。")
        label = version(entry.get("label_key"))
        name = entry.get("display_name")
        definition = entry.get("definition")
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise click.ClickException("类别显示名称须为1至64位文本。")
        if definition is not None and (not isinstance(definition, str) or len(definition) > 512):
            raise click.ClickException("类别定义须为不超过512位文本。")
        rows.append(dict(category_version=category_version, id=entry["id"], label_key=label, display_name=name, definition=definition))
    if {row["id"] for row in rows} != set(range(10)) or len({row["label_key"] for row in rows}) != 10:
        raise click.ClickException("类别ID须为0至9且标签键不可重复。")
    existing = db.session.scalars(select(Category).where(Category.category_version == category_version)).all()
    if existing:
        actual = {row.id: {field: getattr(row, field) for field in rows[0]} for row in existing}
        expected = {row["id"]: row for row in rows}
        if actual != expected:
            raise click.ClickException("该类别版本已有不同内容，拒绝覆盖。")
        return category_version, False
    db.session.add_all(Category(**row) for row in rows)
    db.session.commit()
    return category_version, True


def register_model(data):
    model_version = version(data.get("model_version"))
    category_version = version(data.get("category_version"))
    fields = dict(version=model_version, category_version=category_version)
    for key, field in (("sha256", "model_sha256"), ("labels_sha256", "labels_sha256")):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise click.ClickException(f"{key}须为64位SHA-256。")
        fields[field] = value.lower()
    if data.get("status") not in ("experimental", "frozen"):
        raise click.ClickException("模型状态须为experimental或frozen。")
    threshold = data.get("low_confidence_threshold")
    if type(threshold) not in (int, float) or not 0 <= threshold <= 1:
        raise click.ClickException("低置信阈值须为0至1的有限数值。")
    fields.update(release_status=data["status"], low_confidence_threshold=float(threshold))
    categories = db.session.scalars(select(Category).where(Category.category_version == category_version).order_by(Category.id)).all()
    if [row.id for row in categories] != list(range(10)):
        raise click.ClickException("请先导入模型对应的完整类别版本。")
    if "categories" in data:
        declared = data["categories"]
        expected = [(row.id, row.label_key) for row in categories]
        if not isinstance(declared, list) or not all(isinstance(item, dict) for item in declared) or [(item.get("id"), item.get("label_key")) for item in declared] != expected:
            raise click.ClickException("模型类别顺序与已登记类别不一致。")
    existing = db.session.get(ModelVersion, model_version)
    if existing is not None:
        if any(getattr(existing, key) != value for key, value in fields.items()):
            raise click.ClickException("该模型版本已有不同元数据，拒绝覆盖。")
        return model_version, False
    db.session.add(ModelVersion(**fields))
    db.session.commit()
    return model_version, True


def register_commands(app):
    @app.cli.command("db-schema")
    @click.option("--output", type=click.Path(path_type=Path, dir_okay=False))
    def db_schema(output):
        """Render the initial MySQL SQL without making a connection."""
        schema = render_mysql_schema()
        if output is None:
            click.echo(schema, nl=False)
        else:
            output.write_text(schema, encoding="utf-8")
            click.echo(f"Schema written to {output}")

    @app.cli.command("db-init")
    def db_init():
        """Create missing tables in an already-created MySQL database."""
        try:
            if db.engine.dialect.name != "mysql":
                raise click.ClickException("db-init仅用于MySQL。")
            server_version = db.session.execute(text("SELECT VERSION()")).scalar_one()
            parts = re.match(r"(\d+)\.(\d+)\.(\d+)", server_version)
            if "MariaDB" in server_version or not parts or tuple(map(int, parts.groups())) < (8, 0, 16):
                raise click.ClickException("需要MySQL 8.0.16或更高版本以执行CHECK约束。")
            db.session.rollback()
            db.create_all()
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise click.ClickException("建表失败，请检查数据库是否已创建、连接配置及DDL权限。") from exc
        click.echo("Created missing core tables; existing tables/data were preserved. This is not a migration.")

    @app.cli.command("db-seed")
    @click.option("--categories", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=DEFAULT_CATEGORIES, show_default=True)
    def db_seed(categories):
        """Register frozen categories without overwriting an existing version."""
        try:
            name, created = seed_categories(read_object(categories))
        except (SQLAlchemyError, click.ClickException) as exc:
            db.session.rollback()
            if isinstance(exc, click.ClickException):
                raise
            raise click.ClickException("类别导入失败，请检查连接及数据库结构。") from exc
        click.echo(f"Categories {name}: {'created' if created else 'already registered'}")

    @app.cli.command("register-model")
    @click.option("--metadata", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
    def register_model_command(metadata):
        """Register model metadata only; no model binary is loaded."""
        try:
            name, created = register_model(read_object(metadata))
        except (SQLAlchemyError, click.ClickException) as exc:
            db.session.rollback()
            if isinstance(exc, click.ClickException):
                raise
            raise click.ClickException("模型登记失败，请检查连接及数据库结构。") from exc
        click.echo(f"Model {name}: {'created' if created else 'already registered'} (metadata only)")
