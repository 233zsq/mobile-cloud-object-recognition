"""Imports and CLI help cannot accidentally start a collection/training/backup job."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = [
    "campaign",
    "runtime_check",
    "handover",
    "source_provenance",
    "delivery",
    "collect_increment",
    "product_cli",
    "scope_cli",
    "scope_data",
    "scope_training",
    "scope_features",
    "scope_recheck",
    "scope_release",
    "scope_handover",
    "scope_verification",
    "placeholder",
    "official_model",
    "legacy_data",
]
COMMANDS = [
    "run-ml-campaign.py",
    "check-local-runtime.py",
    "make-handover-report.py",
    "record-source-commit.py",
    "package-ml-delivery.py",
    "collect-evolution-candidates.py",
    "collect-product-candidates.py",
    "probe-scope-policy.py",
    "prepare-open-set-data.py",
    "train-open-set.py",
    "probe-open-set.py",
    "recheck-open-set-seed.py",
    "package-open-set.py",
    "prepare-open-set-handover.py",
    "verify-open-set.py",
    "sync-configs.py",
    "check-project.py",
    "download_database_backup.py",
    "package-web.py",
]


def test_importing_implementations_has_no_task_side_effects():
    code = """
import argparse, importlib, importlib.abc, os, pathlib, subprocess, sys, urllib.request
sys.path[:0] = [str(pathlib.Path.cwd()), str(pathlib.Path.cwd() / 'ml/src')]
class NoTrainingDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('numpy', 'PIL', 'tensorflow', 'keras'):
            raise AssertionError('Import started an optional runtime: ' + fullname)
sys.meta_path.insert(0, NoTrainingDependencies())
def forbidden(*args, **kwargs):
    raise AssertionError('Import started work')
argparse.ArgumentParser.parse_args = forbidden
subprocess.run = subprocess.check_output = forbidden
urllib.request.urlopen = forbidden
pathlib.Path.mkdir = pathlib.Path.write_text = pathlib.Path.write_bytes = forbidden
before = dict(os.environ)
for name in %r:
    importlib.import_module(name)
assert dict(os.environ) == before
""" % (
        ["recognition." + name for name in DOMAIN]
        + [
            "tools.checks",
            "tools.config.cli",
            "tools.config.distribution",
            "tools.database_backup",
            "tools.brand_assets",
            "tools.web_bundle",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", COMMANDS)
def test_cli_help_does_not_require_or_run_optional_work(script):
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_configuration_compatibility_import_preserves_module_identity():
    sys.path.insert(0, str(ROOT / "scripts"))
    import config_distribution
    from tools.config import distribution

    assert config_distribution is distribution


@pytest.mark.parametrize("mode", ["reference_tensor", "image_chain"])
def test_handover_command_never_copies_golden_scores_as_device_evidence(tmp_path, mode):
    import json

    bundle = tmp_path / "release"
    (bundle / "examples").mkdir(parents=True)
    metadata = {
        "sha256": "a" * 64,
        "labels_sha256": "b" * 64,
        "input": {"version": "rgb-letterbox-v1"},
    }
    (bundle / "metadata.json").write_text(json.dumps(metadata))
    (bundle / "examples/manifest.json").write_text(
        json.dumps([{"sample_id": "cup-1", "scores": [0.9] + [0.1 / 9] * 9}])
    )
    output = tmp_path / "blank-device-result.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/make-handover-report.py"),
            "--release",
            str(bundle),
            "--mode",
            mode,
            "--out",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    form = json.loads(output.read_text())
    assert form["samples"][0]["scores"] == [None] * 10
    assert form["model_sha256"] == metadata["sha256"]
    assert form["labels_sha256"] == metadata["labels_sha256"]
    before = output.read_bytes()
    retry = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/make-handover-report.py"),
            "--release",
            str(bundle),
            "--mode",
            mode,
            "--out",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert retry.returncode != 0
    assert output.read_bytes() == before
