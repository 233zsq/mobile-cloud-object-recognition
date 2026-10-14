"""Load environment defaults and frozen category/model resources per app."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from . import ai_triage
from .paths import ROOT
from .utils import sha


@dataclass(frozen=True)
class ReviewResources:
    data: Path
    categories: dict
    category_bytes: bytes
    queue_category_hashes: frozenset[str]
    baseline: dict
    base_metrics: dict


def configure(app, config=None):
    app.config.update(
        SECRET_KEY=os.environ.get("REVIEW_SECRET_KEY"),
        DATA_DIR=os.environ.get("REVIEW_DATA_DIR", str(ROOT / "var")),
        MAX_CONTENT_LENGTH=9 * 1024 * 1024,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=28800,
        REVIEW_LEASE_SECONDS=900,
        REVIEW_AI_KEY_FILE=os.environ.get("REVIEW_AI_KEY_FILE", ""),
        REVIEW_AI_BUDGET_NANO=int(
            os.environ.get("REVIEW_AI_BUDGET_NANO", "1000000000")
        ),
        REVIEW_AI_MAX_CALLS=int(os.environ.get("REVIEW_AI_MAX_CALLS", "500")),
        REVIEW_AI_AUDIT_PERCENT=int(os.environ.get("REVIEW_AI_AUDIT_PERCENT", "5")),
        REVIEW_TRIAGE_PRIMARY_MODEL=os.environ.get(
            "REVIEW_TRIAGE_PRIMARY_MODEL", "qwen3.8-flash"
        ),
        REVIEW_TRIAGE_POLICY=os.environ.get(
            "REVIEW_TRIAGE_POLICY", ai_triage.CASCADE_POLICY
        ),
        EGRESS_LIMIT_BYTES=int(
            float(os.environ.get("REVIEW_EGRESS_LIMIT_GIB", "20")) * 1024**3
        ),
        TRUSTED_HOSTS=["49.232.195.47", "127.0.0.1", "localhost"],
    )
    if config:
        app.config.update(config)
    if not app.secret_key or len(app.secret_key) < 32:
        raise ValueError("Set REVIEW_SECRET_KEY to at least 32 random characters")
    data = Path(app.config["DATA_DIR"]).resolve()
    data.mkdir(parents=True, exist_ok=True)
    for name in ("images", "previews", "thumbs", "details", "batches"):
        (data / name).mkdir(exist_ok=True)
    categories_file = Path(
        app.config.get(
            "CATEGORIES_FILE",
            ROOT.parent / "shared/category-versions/campus-10-v4.json",
        )
    )
    category_bytes = categories_file.read_bytes()
    cat = json.loads(category_bytes)
    queue_category_hashes = {sha(category_bytes)}
    mapping = lambda value: [(c["id"], c["label_key"]) for c in value["categories"]]
    # Old public queues contain suggestions only; all imported images need review.
    compatible = {
        ("campus-10-v2", "campus-10-v3"),
        ("campus-10-v2", "campus-10-v4"),
        ("campus-10-v3", "campus-10-v4"),
    }
    for legacy_file in (
        ROOT.parent / "shared/categories.json",
        ROOT.parent / "shared/category-versions/campus-10-v3.json",
    ):
        legacy_bytes = legacy_file.read_bytes()
        legacy_cat = json.loads(legacy_bytes)
        if (
            legacy_cat["category_version"],
            cat["category_version"],
        ) in compatible and mapping(legacy_cat) == mapping(cat):
            queue_category_hashes.add(sha(legacy_bytes))
    baseline = json.loads(
        (ROOT.parent / "models/releases/campus-gpu-v1/metadata.json").read_text(
            encoding="utf-8"
        )
    )
    base_metrics = json.loads(
        (
            ROOT.parent / "models/releases/campus-gpu-v1/evaluation-validation.json"
        ).read_text(encoding="utf-8")
    )["metrics"]
    app.config["REVIEW_AI_CATEGORY_SHA256"] = sha(category_bytes)
    return ReviewResources(
        data,
        cat,
        category_bytes,
        frozenset(queue_category_hashes),
        baseline,
        base_metrics,
    )
