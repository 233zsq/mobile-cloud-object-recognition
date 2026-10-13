"""Shared synthetic workspaces; dependencies load only when a fixture is requested."""

import pytest


@pytest.fixture
def data_workspace(tmp_path, monkeypatch):

    import numpy as np
    from PIL import Image
    from recognition import common, data

    original = common.categories()
    monkeypatch.setattr(common, "ROOT", tmp_path)
    monkeypatch.setattr(data, "ROOT", tmp_path)
    common.write_json(tmp_path / "shared/categories.json", original)
    rows = []
    rng = np.random.default_rng(123)
    for c in range(10):
        for i in range(4):
            path = tmp_path / f"data/raw/c{c}-{i}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rng.integers(0, 256, (150, 200, 3), dtype=np.uint8)).save(
                path
            )
            row = {k: "" for k in common.FIELDS}
            row.update(
                sample_id=f"c{c}-{i}",
                image_path=path.relative_to(tmp_path).as_posix(),
                image_sha256=common.digest(path),
                category_id=str(c),
                group_id=f"c{c}-g{i // 2}",
                review_status="approved",
            )
            rows.append(row)
    manifest = tmp_path / "data/manifests/samples.csv"
    common.write_csv(manifest, rows)
    return tmp_path, manifest, rows


@pytest.fixture
def evolution_workspace(tmp_path, monkeypatch):
    import csv
    import hashlib
    import io
    import json
    from pathlib import Path
    import zipfile

    import numpy as np
    from PIL import Image
    from recognition import common, data, evolution, training, release

    source = common.ROOT
    for module in (common, data, evolution, training, release):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared/categories.json").write_bytes(
        (source / "shared/categories.json").read_bytes()
    )
    (tmp_path / "shared/category-versions").mkdir()
    for version in ("campus-10-v3", "campus-10-v4"):
        policy = Path("shared/category-versions") / (version + ".json")
        (tmp_path / policy).write_bytes((source / policy).read_bytes())
    common.write_json(
        tmp_path / "ml/configs/baseline.json",
        common.read_json(source / "ml/configs/baseline.json"),
    )
    parent = tmp_path / "experiments/checkpoints/parent/best.keras"
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b"test-only-parent")
    common.write_json(
        tmp_path / "models/releases/campus-gpu-v1/metadata.json",
        {
            "status": "frozen",
            "category_version": "campus-10-v2",
            "experiment_id": "parent",
            "data_version": "base",
            "checkpoint_sha256": common.digest(parent),
            "sha256": "a" * 64,
        },
    )
    rng = np.random.default_rng(3)

    def row(sid, category=0):
        path = tmp_path / "data/raw" / (sid + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rng.integers(0, 256, (128, 128, 3), np.uint8)).save(path)
        with Image.open(path) as im:
            fingerprint = data.phash(im)
        return {
            "sample_id": sid,
            "image_path": path.relative_to(tmp_path).as_posix(),
            "image_sha256": common.digest(path),
            "category_id": str(category),
            "object_id": sid,
            "session_id": "test-session",
            "group_id": sid,
            "phash": fingerprint,
            "review_status": "approved",
            "source_dataset": "field",
        }

    metadata = {
        "status": "frozen",
        "data_version": "base",
        "category_version": "campus-10-v2",
        "categories_sha256": common.digest(tmp_path / "shared/categories.json"),
        "files": {},
    }
    for name in ("train", "validation"):
        rows = [row(name + str(i), i) for i in range(10)]
        for r in rows:
            r.update(
                split_name=name,
                data_version="base",
                source_dataset="public-test-fixture",
            )
        path = tmp_path / "data/splits/base" / (name + ".csv")
        common.write_csv(path, rows)
        metadata["files"][name] = {"sha256": common.digest(path), "count": 10}
    common.write_json(tmp_path / "data/splits/base/dataset.json", metadata)

    def archive(rows, name="batch.zip", category_version="campus-10-v2"):
        records = [
            {**r, "image_path": "images/" + Path(r["image_path"]).name} for r in rows
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
        payload = stream.getvalue().encode()
        receipt = {
            "purpose": "training_only",
            "category_version": category_version,
            "categories_sha256": common.digest(common.category_path(category_version)),
            "batch_id": "test-batch",
            "count": len(rows),
            "files": {
                "samples.csv": hashlib.sha256(payload).hexdigest(),
                **{r["image_path"]: r["image_sha256"] for r in records},
            },
        }
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("batch.json", json.dumps(receipt))
            z.writestr("samples.csv", payload)
            for a, b in zip(rows, records):
                z.write(tmp_path / a["image_path"], b["image_path"])
        return path

    return tmp_path, row, archive
