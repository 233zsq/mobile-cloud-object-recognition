"""Core entities; initial SQL is generated from this metadata."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Double, ForeignKeyConstraint
from sqlalchemy import Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.functions import FunctionElement

from ..extensions import db


def identifier(length):
    return String(length).with_variant(
        mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"), "mysql"
    )


timestamp = DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
table_options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}


class ServerTimestamp(FunctionElement):
    type = DateTime()
    inherit_cache = True


@compiles(ServerTimestamp)
def default_timestamp(element, compiler, **kwargs):
    return "CURRENT_TIMESTAMP"


@compiles(ServerTimestamp, "mysql")
def mysql_timestamp(element, compiler, **kwargs):
    return "CURRENT_TIMESTAMP(3)"


class Category(db.Model):
    __tablename__ = "category"
    category_version: Mapped[str] = mapped_column(identifier(64), primary_key=True)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    label_key: Mapped[str] = mapped_column(identifier(64))
    display_name: Mapped[str] = mapped_column(String(64))
    definition: Mapped[str | None] = mapped_column(String(512))
    __table_args__ = (
        UniqueConstraint("category_version", "label_key", name="uq_category_label"),
        CheckConstraint("id >= 0 AND id <= 9", name="ck_category_id"),
        table_options,
    )


class ModelVersion(db.Model):
    __tablename__ = "model_version"
    version: Mapped[str] = mapped_column(identifier(64), primary_key=True)
    category_version: Mapped[str] = mapped_column(identifier(64))
    model_sha256: Mapped[str] = mapped_column(identifier(64))
    labels_sha256: Mapped[str] = mapped_column(identifier(64))
    release_status: Mapped[str] = mapped_column(identifier(16))
    low_confidence_threshold: Mapped[float] = mapped_column(Double)
    registered_at: Mapped[datetime] = mapped_column(timestamp, server_default=ServerTimestamp())
    __table_args__ = (
        UniqueConstraint("version", "category_version", name="uq_model_category_version"),
        CheckConstraint("release_status IN ('experimental', 'frozen')", name="ck_model_status"),
        CheckConstraint("low_confidence_threshold >= 0 AND low_confidence_threshold <= 1", name="ck_model_threshold"),
        table_options,
    )


class InferenceRecord(db.Model):
    __tablename__ = "inference_record"
    record_id: Mapped[str] = mapped_column(identifier(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(identifier(36))
    inference_source: Mapped[str] = mapped_column(identifier(16))
    model_version: Mapped[str] = mapped_column(identifier(64))
    category_version: Mapped[str] = mapped_column(identifier(64))
    predicted_id: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Double)
    latency_ms: Mapped[int] = mapped_column(BigInteger)
    captured_at: Mapped[datetime] = mapped_column(timestamp)
    payload_sha256: Mapped[str] = mapped_column(identifier(64))
    corrected_id: Mapped[int | None] = mapped_column(Integer)
    corrected_at: Mapped[datetime | None] = mapped_column(timestamp)
    revision: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(timestamp, server_default=ServerTimestamp())
    __table_args__ = (
        ForeignKeyConstraint(["model_version", "category_version"], ["model_version.version", "model_version.category_version"], name="fk_record_model"),
        ForeignKeyConstraint(["category_version", "predicted_id"], ["category.category_version", "category.id"], name="fk_record_prediction"),
        ForeignKeyConstraint(["category_version", "corrected_id"], ["category.category_version", "category.id"], name="fk_record_correction"),
        CheckConstraint("inference_source IN ('device', 'cloud')", name="ck_record_source"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_record_confidence"),
        CheckConstraint("latency_ms >= 0", name="ck_record_latency"),
        CheckConstraint("revision >= 0", name="ck_record_revision"),
        CheckConstraint("(corrected_id IS NULL AND corrected_at IS NULL AND revision = 0) OR (corrected_id IS NOT NULL AND corrected_at IS NOT NULL AND revision > 0)", name="ck_record_correction_state"),
        Index("ix_record_captured", "captured_at"),
        Index("ix_record_model_captured", "model_version", "captured_at"),
        table_options,
    )


class Sample(db.Model):
    __tablename__ = "sample"
    sample_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    image_path: Mapped[str] = mapped_column(String(512))
    image_sha256: Mapped[str] = mapped_column(identifier(64), index=True)
    category_version: Mapped[str] = mapped_column(identifier(64))
    category_id: Mapped[int] = mapped_column(Integer)
    object_id: Mapped[str | None] = mapped_column(String(128))
    session_id: Mapped[str | None] = mapped_column(String(128))
    collector: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime | None] = mapped_column(timestamp)
    split_name: Mapped[str | None] = mapped_column(identifier(16))
    review_status: Mapped[str] = mapped_column(identifier(16), server_default=text("'pending'"))
    data_version: Mapped[str | None] = mapped_column(identifier(64))
    __table_args__ = (
        ForeignKeyConstraint(["category_version", "category_id"], ["category.category_version", "category.id"], name="fk_sample_category"),
        CheckConstraint("split_name IS NULL OR split_name IN ('train', 'validation', 'test')", name="ck_sample_split"),
        CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name="ck_sample_review"),
        table_options,
    )
