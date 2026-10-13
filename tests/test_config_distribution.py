"""Distribution, version compatibility and immutable-byte regression checks."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config_distribution as distribution

sys.path.insert(0, str(ROOT / "ml/src"))
from recognition import common


def snapshot(root):
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def assert_preserved(root, original):
    assert {path: (root / path).read_bytes() for path in original} == original


@pytest.fixture
def workspace(tmp_path):
    catalog = distribution.Catalog(ROOT)
    files = {
        "shared/config-distribution.json",
        "scripts/config_distribution.py",
        "scripts/sync-configs.py",
        "tools/__init__.py",
        "tools/config/__init__.py",
        "tools/config/cli.py",
        "tools/config/distribution.py",
        *catalog.targets()[0],
    }
    for entry in catalog.index["categories"].values():
        files.add(entry["file"])
    for entry in catalog.index["policies"].values():
        files.update((entry["file"], entry["checksum_file"]))
    for key, entry in catalog.index["models"].items():
        files.update((entry["metadata_file"], entry["labels_file"]))
        filename = catalog.models[key][0].get("scope_policy_file")
        if filename:
            files.add(str(Path(entry["metadata_file"]).parent / filename))
    for filename in files:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, target)
    return tmp_path


def update_index(root, mutate):
    path = root / "shared/config-distribution.json"
    value = json.loads(path.read_bytes())
    mutate(value)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def run_cli(root, *arguments):
    return subprocess.run(
        [sys.executable, str(root / "scripts/sync-configs.py"), *arguments], capture_output=True, text=True, cwd=root
    )


def test_current_distribution_is_byte_identical_and_generate_is_a_noop(workspace):
    catalog = distribution.Catalog(workspace)
    original = snapshot(workspace)
    assert len(catalog.categories) == 4 and len(catalog.models) == 3 and len(catalog.policies) == 2
    assert len(catalog.targets()[0]) == 8
    assert catalog.check() == [] and catalog.generate() == []
    assert_preserved(workspace, original)


@pytest.mark.parametrize(
    "category,model",
    [
        ("campus-10-v1", None),
        ("campus-10-v2", None),
        ("campus-10-v3", None),
        ("campus-10-v4", None),
        ("campus-10-v2", "campus-gpu-v1"),
        ("campus-10-v4", "campus-evolve-v2"),
        ("campus-10-v4", "campus-evolve-v3"),
    ],
)
def test_explicit_export_preserves_sources_versions_label_order_and_checksums(workspace, category, model):
    catalog = distribution.Catalog(workspace)
    original = snapshot(workspace)
    output = workspace / "delivery"
    receipt = catalog.export(output, category, model)
    assert (output / "categories.json").read_bytes() == catalog.categories[category][1]
    assert (output / "labels.txt").read_text(encoding="utf-8").splitlines() == list(catalog.labels)
    assert receipt["category_version"] == category and receipt["model_version"] == model
    assert receipt["category_sha256"] == hashlib.sha256(catalog.categories[category][1]).hexdigest()
    for name, checksum in receipt["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == checksum
    if model is not None:
        meta = catalog.models[model][0]
        contract = json.loads((output / "model-contract.json").read_bytes())
        assert contract["model_version"] == model and contract["model_sha256"] == meta["sha256"]
        assert contract["category_version"] == category
        assert receipt["files"]["labels.txt"] == meta["labels_sha256"]
        policy = catalog.index["models"][model]["policy_version"]
        if policy is not None:
            assert (output / "scope-policy.json").read_bytes() == catalog.policies[policy][1]
            assert (output / "scope-policy.sha256").read_bytes() == catalog.policies[policy][2]
            assert contract["scope_policy_sha256"] == receipt["files"]["scope-policy.json"]
            assert contract["scope_policy_newline"] == ("CRLF" if model == "campus-evolve-v2" else "LF")
        else:
            assert contract["scope_policy"] is None and not (output / "scope-policy.json").exists()
    assert_preserved(workspace, original)


@pytest.mark.parametrize(
    "filename",
    [
        "android/app/src/main/assets/categories.json",
        "android/app/src/main/assets/scope/scope-policy.json",
        "android/app/src/main/assets/scope/scope-policy.sha256",
        "backend/policies/scope-basic-v1.json",
        "web/ios/categories.json",
        "web/ios/model-contract.json",
    ],
)
def test_check_reports_drift_and_generate_restores_only_the_affected_copy(workspace, filename):
    original = snapshot(workspace)
    (workspace / filename).write_bytes(b"corrupt copy")
    catalog = distribution.Catalog(workspace)
    (difference,) = catalog.check()
    assert difference["path"] == filename and difference["actual_sha256"] != difference["expected_sha256"]
    assert catalog.generate() == [filename]
    assert catalog.check() == []
    assert_preserved(workspace, original)


@pytest.mark.parametrize("filename", ["shared/categories.json", "database/seeds/categories.campus-10-v2.json"])
def test_historical_compatibility_drift_is_reported_and_never_overwritten(workspace, filename):
    (workspace / filename).write_bytes(b"historical bytes requiring investigation")
    (workspace / "web/ios/categories.json").write_bytes(b"pending mutable repair")
    original = snapshot(workspace)
    catalog = distribution.Catalog(workspace)
    assert filename in {item["path"] for item in catalog.check()}
    with pytest.raises(ValueError, match="Immutable compatibility"):
        catalog.generate(("web",))
    assert_preserved(workspace, original)


def test_changed_source_hash_prevents_generation_without_touching_copies(workspace):
    source = workspace / "shared/category-versions/campus-10-v4.json"
    source.write_bytes(source.read_bytes() + b" ")
    original = snapshot(workspace)
    with pytest.raises(ValueError, match="Source SHA-256 mismatch"):
        distribution.Catalog(workspace).generate()
    assert_preserved(workspace, original)


@pytest.mark.parametrize(
    "fault", ["category_order", "model_labels", "policy_identity", "published_policy", "policy_checksum"]
)
def test_semantic_identity_checks_remain_effective_after_source_repinning(workspace, fault):
    if fault == "category_order":
        source = workspace / "shared/category-versions/campus-10-v4.json"
        value = json.loads(source.read_bytes())
        value["categories"][0]["label_key"], value["categories"][1]["label_key"] = (
            value["categories"][1]["label_key"],
            value["categories"][0]["label_key"],
        )
        source.write_text(json.dumps(value) + "\n", encoding="utf-8")
        update_index(
            workspace, lambda i: i["categories"]["campus-10-v4"].update(sha256=distribution.sha256(source.read_bytes()))
        )
    elif fault == "model_labels":
        source = workspace / "models/releases/campus-evolve-v2/labels.txt"
        source.write_bytes(b"wrong\n" + source.read_bytes())
        update_index(
            workspace,
            lambda i: i["models"]["campus-evolve-v2"].update(labels_sha256=distribution.sha256(source.read_bytes())),
        )
    elif fault == "policy_identity":
        source = workspace / "shared/policies/scope-basic-v1/scope-policy.json"
        value = json.loads(source.read_bytes())
        value["model_sha256"] = "0" * 64
        source.write_text(json.dumps(value) + "\n", encoding="utf-8")
        checksum = distribution.sha256(source.read_bytes())
        source.with_suffix(".sha256").write_text(checksum + "\n", encoding="ascii")
        update_index(workspace, lambda i: i["policies"]["scope-basic-v1"].update(sha256=checksum))
    elif fault == "published_policy":
        source = workspace / "models/releases/campus-evolve-v3/scope-policy.json"
        source.write_bytes(source.read_bytes() + b" ")
    else:
        (workspace / "shared/policies/scope-basic-v1/scope-policy.sha256").write_text("0" * 64 + "\n", encoding="ascii")
    original = snapshot(workspace)
    with pytest.raises(ValueError, match="mismatch|differs"):
        distribution.Catalog(workspace).generate()
    assert_preserved(workspace, original)


@pytest.mark.parametrize(
    "category,model,policy",
    [
        ("campus-10-v2", "campus-evolve-v3", None),
        ("campus-10-v4", "campus-evolve-v2", "scope-knownness-v1"),
        ("campus-10-v4", None, "scope-basic-v1"),
    ],
)
def test_mixed_export_versions_fail_before_creating_a_directory(workspace, category, model, policy):
    output = workspace / "mixed"
    with pytest.raises(ValueError):
        distribution.Catalog(workspace).export(output, category, model, policy)
    assert not output.exists()


def test_existing_export_directory_is_never_overwritten(workspace):
    output = workspace / "delivery"
    output.mkdir()
    (output / "receipt.txt").write_bytes(b"previous delivery")
    original = snapshot(workspace)
    with pytest.raises(FileExistsError):
        distribution.Catalog(workspace).export(output, "campus-10-v4", "campus-evolve-v3")
    assert_preserved(workspace, original)


def test_write_failure_rolls_back_already_repaired_targets(workspace, monkeypatch):
    for filename in ("web/ios/categories.json", "web/ios/model-contract.json"):
        (workspace / filename).write_bytes(b"previous copy")
    original = snapshot(workspace)
    write = distribution.atomic_write
    calls = []

    def fail_once(path, content):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("simulated replacement error")
        write(path, content)

    monkeypatch.setattr(distribution, "atomic_write", fail_once)
    with pytest.raises(OSError, match="simulated"):
        distribution.Catalog(workspace).generate(("web",))
    assert len(calls) == 3
    assert_preserved(workspace, original)
    assert not list(workspace.rglob("*.tmp"))


def test_source_paths_cannot_escape_the_repository(workspace):
    update_index(workspace, lambda i: i["categories"]["campus-10-v4"].update(file="../outside.json"))
    with pytest.raises(ValueError, match="repository-relative"):
        distribution.Catalog(workspace)


def test_cli_check_generate_target_and_version_export(workspace):
    result = run_cli(workspace, "check")
    assert result.returncode == 0 and json.loads(result.stdout)["ok"]
    (workspace / "web/ios/categories.json").write_bytes(b"drift")
    result = run_cli(workspace, "check", "--target", "web")
    assert result.returncode == 1 and not json.loads(result.stdout)["ok"]
    result = run_cli(workspace, "generate", "--target", "web")
    assert result.returncode == 0 and json.loads(result.stdout)["changed"] == ["web/ios/categories.json"]
    result = run_cli(
        workspace,
        "export",
        "--category-version",
        "campus-10-v4",
        "--model-version",
        "campus-evolve-v3",
        "--output",
        "delivery",
    )
    assert result.returncode == 0 and json.loads(result.stdout)["policy_version"] == "scope-knownness-v1"


def test_selected_generate_does_not_repair_other_mutable_groups(workspace):
    (workspace / "web/ios/categories.json").write_bytes(b"web drift")
    (workspace / "android/app/src/main/assets/categories.json").write_bytes(b"android drift")
    catalog = distribution.Catalog(workspace)
    assert catalog.generate(("web",)) == ["web/ios/categories.json"]
    assert (workspace / "android/app/src/main/assets/categories.json").read_bytes() == b"android drift"


def test_ml_uses_explicit_archive_and_keeps_implicit_legacy_default(workspace, monkeypatch):
    monkeypatch.setattr(common, "ROOT", workspace)
    assert common.category_path("campus-10-v2") == workspace / "shared/category-versions/campus-10-v2.json"
    assert common.category_path() == workspace / "shared/categories.json"
    assert common.categories("campus-10-v2") == common.categories()


def test_historical_ml_workspace_without_v2_archive_remains_reproducible(workspace, monkeypatch):
    monkeypatch.setattr(common, "ROOT", workspace)
    (workspace / "shared/category-versions/campus-10-v2.json").unlink()
    assert common.category_path("campus-10-v2") == workspace / "shared/categories.json"
    assert common.categories("campus-10-v2")["category_version"] == "campus-10-v2"
