import shutil
import os
import subprocess
import sys
from pathlib import Path

import pytest
from recognition.common import read_json, write_json

from recognition import reports

REPO = Path(__file__).resolve().parents[2]
CASES = [
    ("pilot-cpu", "pilot-cpu-20261007", "pilot-cpu-tuned-v1", "write-ml-report.py", "ml-experiments.md"),
    (
        "expanded-cpu",
        "expanded-cpu-20261007",
        "expanded-cpu-v1",
        "write-expanded-ml-report.py",
        "ml-expanded-experiments.md",
    ),
    ("gpu", "expanded-gpu-20261008", "campus-gpu-v1", "write-gpu-ml-report.py", "ml-gpu-experiments.md"),
]


def report_workspace(directory, case):
    """Copy recorded inputs into an isolated root; no models or training are needed."""
    profile, campaign, version, script, document = case
    winner = read_json(REPO / "experiments/reports" / campaign / "fine_tune-summary.json")["winner"]
    meta = read_json(REPO / "models/releases" / version / "metadata.json")
    data_version = winner["config"]["data_version"] if profile == "pilot-cpu" else meta["data_version"]
    paths = [
        Path("scripts/write-report.py"),
        Path("scripts") / script,
        Path("experiments/reports/implementation-status.json"),
        Path("shared/categories.json"),
        Path("data/splits") / data_version / "dataset.json",
        Path("experiments/reports") / (winner["experiment_id"] + "-repeat43") / "result.json",
        *[Path("experiments/reports") / campaign / (stage + "-summary.json") for stage in reports.STAGES],
        *[
            Path("models/releases") / version / name
            for name in ("metadata.json", "labels.txt", "release-files.json", "validation-comparison.json")
        ],
    ]
    if profile == "pilot-cpu":
        paths.append(Path("data/manifests/public-reviewed.csv"))
    else:
        paths.extend(
            [
                Path("experiments/reports/benchmarks") / version / "local-cpu-1threads.json",
                Path("experiments/reports/audit/final-public-data.json"),
            ]
        )
    if profile == "gpu":
        paths.extend(
            path.relative_to(REPO)
            for path in (REPO / "experiments/reports/environment").glob(f"standalone-*{version}-*.json")
        )
    for path in paths:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / path, target)
    for name in ("__init__.py", "common.py", "manifest_io.py", "reports.py"):
        target = directory / "ml/src/recognition" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "ml/src/recognition" / name, target)
    (directory / "docs").mkdir()
    return {path: (directory / path).read_bytes() for path in paths}


def run_report(directory, script, arguments=()):
    environment = {**os.environ, "RECOGNITION_ROOT": str(directory)}
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(directory / "scripts" / script), *arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        encoding="utf-8",
    )


def normalized(document):
    import re

    return re.sub(r"生成时间：[^。]+。", "生成时间：<timestamp>。", document, count=1)


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
@pytest.mark.parametrize("entry", ["compatibility", "unified"])
def test_recorded_report_matches_pre_refactor_output_and_preserves_inputs(tmp_path, case, entry):
    profile, campaign, version, script, document = case
    original = report_workspace(tmp_path, case)
    arguments = ["--campaign", campaign, "--version", version] if profile == "gpu" else []
    if entry == "unified":
        script = "write-report.py"
        arguments = ["--profile", profile, *arguments]
    result = run_report(tmp_path, script, arguments)
    assert result.returncode == 0, result.stderr
    output = tmp_path / "docs" / document
    assert normalized(output.read_text(encoding="utf-8")) == (REPO / "ml/tests/fixtures/reports" / document).read_text(
        encoding="utf-8"
    )
    assert Path(result.stdout.strip()) == output
    assert {path: (tmp_path / path).read_bytes() for path in original} == original


@pytest.mark.parametrize("profile", ["expanded-cpu", "gpu"])
def test_large_repeat_gap_requires_seed44_and_renders_its_recorded_metrics(tmp_path, profile):
    case = next(case for case in CASES if case[0] == profile)
    report_workspace(tmp_path, case)
    report = reports.load_report(profile, case[1], case[2], root=tmp_path)
    repeat_path = tmp_path / "experiments/reports" / (report.winner["experiment_id"] + "-repeat43") / "result.json"
    repeat = read_json(repeat_path)
    repeat["validation"]["macro_f1"] = report.winner["validation"]["macro_f1"] - 0.1
    write_json(repeat_path, repeat)
    with pytest.raises(FileNotFoundError):
        reports.render_report(profile, case[1], case[2], root=tmp_path)
    extra_path = repeat_path.parent.with_name(report.winner["experiment_id"] + "-repeat44") / "result.json"
    write_json(extra_path, {"validation": {"accuracy": 0.8123, "macro_f1": 0.7654}})
    content = reports.render_report(profile, case[1], case[2], root=tmp_path)
    assert "种子44" in content and "准确率81.23%" in content and "宏F1=0.7654" in content
    assert "无需追加种子44" not in content


@pytest.mark.parametrize(
    "fault",
    [
        "experimental",
        "experiment",
        "no_gpu",
        "tf32",
        "missing_runtime",
        "wrong_hash",
        "installed_tf",
        "imported_tf",
        "failed_check",
    ],
)
def test_gpu_requirements_fail_without_overwriting_report_or_inputs(tmp_path, fault):
    case = CASES[2]
    report_workspace(tmp_path, case)
    metadata = tmp_path / "models/releases" / case[2] / "metadata.json"
    summary = tmp_path / "experiments/reports" / case[1] / "fine_tune-summary.json"
    runtime_paths = sorted((tmp_path / "experiments/reports/environment").glob("standalone-*.json"))
    if fault in ("experimental", "experiment"):
        meta = read_json(metadata)
        meta["status" if fault == "experimental" else "experiment_id"] = fault
        write_json(metadata, meta)
    elif fault in ("no_gpu", "tf32"):
        value = read_json(summary)
        value["winner"]["environment"]["gpu" if fault == "no_gpu" else "tensor_float_32_enabled"] = fault == "tf32"
        write_json(summary, value)
    elif fault == "missing_runtime":
        for path in runtime_paths:
            path.unlink()
    else:
        runtime = read_json(runtime_paths[0])
        if fault == "wrong_hash":
            runtime["model_sha256"] = "0" * 64
        elif fault in ("installed_tf", "imported_tf"):
            runtime["tensorflow_installed" if fault == "installed_tf" else "tensorflow_imported"] = True
        else:
            runtime["results"][0]["external"]["passed"] = False
        write_json(runtime_paths[0], runtime)
    target = tmp_path / "docs/ml-gpu-experiments.md"
    target.write_bytes(b"previous accepted report")
    original = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    result = run_report(tmp_path, "write-report.py", ["--profile", "gpu", "--campaign", case[1], "--version", case[2]])
    assert result.returncode != 0
    assert "Chapter requires" in result.stderr or "Independent runtime evidence" in result.stderr
    assert {path: path.read_bytes() for path in original} == original


def test_unified_entry_can_write_a_separate_markdown_output(tmp_path):
    case = CASES[0]
    report_workspace(tmp_path, case)
    target = tmp_path / "separate.md"
    result = run_report(tmp_path, "write-report.py", ["--profile", "pilot-cpu", "--output", str(target)])
    assert result.returncode == 0, result.stderr
    assert normalized(target.read_text(encoding="utf-8")) == (REPO / "ml/tests/fixtures/reports" / case[4]).read_text(
        encoding="utf-8"
    )
    assert not list((tmp_path / "docs").iterdir())


@pytest.mark.parametrize(
    "arguments",
    [
        ["--profile", "gpu"],
        ["--profile", "gpu", "--campaign", "expanded-gpu-20261008"],
        ["--profile", "pilot-cpu", "--version", "campus-gpu-v1"],
        ["--profile", "pilot-cpu", "--output", "experiments/reports/implementation-status.json"],
        ["--profile", "gpu", "--campaign", "../escape", "--version", "campus-gpu-v1"],
    ],
)
def test_invalid_report_request_does_not_generate_or_modify_documents(tmp_path, arguments):
    original = report_workspace(tmp_path, CASES[0])
    result = run_report(tmp_path, "write-report.py", arguments)
    assert result.returncode != 0
    assert not list((tmp_path / "docs").iterdir())
    assert {path: (tmp_path / path).read_bytes() for path in original} == original


@pytest.mark.parametrize(
    "campaign_name,version,script_name,document",
    [
        ("pilot-cpu-20261007", "pilot-cpu-tuned-v1", "write-ml-report.py", "ml-experiments.md"),
        ("expanded-cpu-20261007", "expanded-cpu-v1", "write-expanded-ml-report.py", "ml-expanded-experiments.md"),
    ],
)
@pytest.mark.parametrize("selected", ["expanded-cpu-v1", "campus-gpu-v1"])
def test_historical_report_does_not_replace_current_release(
    tmp_path, campaign_name, version, script_name, document, selected
):
    repo = Path(__file__).resolve().parents[2]
    campaign = Path("experiments/reports") / campaign_name
    winner = read_json(repo / campaign / "fine_tune-summary.json")["winner"]
    paths = [
        Path("scripts") / script_name,
        Path("data/manifests/public-reviewed.csv"),
        Path("shared/categories.json"),
        Path("experiments/reports/implementation-status.json"),
        Path("data/splits") / winner["config"]["data_version"] / "dataset.json",
        Path("experiments/reports") / (winner["experiment_id"] + "-repeat43") / "result.json",
        *[campaign / (stage + "-summary.json") for stage in ("learning_rate", "dropout", "fine_tune")],
        *[Path("models/releases") / version / name for name in ("metadata.json", "validation-comparison.json")],
    ]
    if script_name == "write-expanded-ml-report.py":
        paths.extend(
            [
                Path("experiments/reports/benchmarks") / version / "local-cpu-1threads.json",
                Path("experiments/reports/audit/final-public-data.json"),
            ]
        )
    shutil.copytree(
        repo / "ml/src/recognition", tmp_path / "ml/src/recognition", ignore=shutil.ignore_patterns("__pycache__")
    )
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / path, destination)
    (tmp_path / "docs").mkdir()
    status = tmp_path / "experiments/reports/implementation-status.json"
    live = read_json(status)
    if selected == "campus-gpu-v1":
        live["release"].update(selected=selected, status="frozen", model_sha256="gpu-model-sha", model_bytes=9000000)
        live["acceptance"]["independent_field_accuracy_and_f1"] = "passed"
        write_json(status, live)
    original = status.read_bytes()
    environment = {**os.environ, "RECOGNITION_ROOT": str(tmp_path), "PYTHONPATH": str(tmp_path / "ml/src")}
    result = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / script_name)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "docs" / document).is_file()
    assert status.read_bytes() == original
