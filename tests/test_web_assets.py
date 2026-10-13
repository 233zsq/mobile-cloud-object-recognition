"""Public native-module closure, bounded archives and immutable bundle output."""

import importlib.util
import json
from pathlib import Path
import shutil
import tarfile

import pytest

from deploy.ios_assets import FILES, ROOT, runtime_files, validate_runtime
from tools.web_bundle import build_bundle


@pytest.fixture
def web_workspace(tmp_path):
    source = ROOT / "web/ios"
    client = tmp_path / "web/ios"
    client.mkdir(parents=True)
    for name in [*FILES, "runtime-files.json"]:
        destination = client / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    return tmp_path


def test_complete_runtime_graph_is_publishable_and_reproducible(
    web_workspace, tmp_path
):
    content = validate_runtime(web_workspace)
    assert set(content) == FILES
    assert b'type="module"' in content["index.html"]
    first = build_bundle(tmp_path / "first.tar.gz", web_workspace)
    second = build_bundle(tmp_path / "second.tar.gz", web_workspace)
    assert first["sha256"] == second["sha256"]
    with tarfile.open(first["path"]) as archive:
        assert {m.name for m in archive} == FILES
        assert all(m.isfile() and m.mode == 0o644 for m in archive)
        assert {m.name: archive.extractfile(m).read() for m in archive} == content
    spec = importlib.util.spec_from_file_location(
        "web_publisher_contract", ROOT / "deploy/scripts/publish_ios.py"
    )
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    assert publisher.bundle_files(Path(first["path"]), first["sha256"]) == content
    original = Path(first["path"]).read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        build_bundle(Path(first["path"]), web_workspace)
    assert Path(first["path"]).read_bytes() == original


@pytest.mark.parametrize("change", ["missing", "unlisted", "traversal"])
def test_incomplete_or_escaping_module_graph_never_creates_a_bundle(
    web_workspace, tmp_path, change
):
    module = web_workspace / "web/ios/modules/views/page.js"
    if change == "missing":
        module.unlink()
    else:
        target = "./unknown.js" if change == "unlisted" else "../../../private.env"
        module.write_text("import '" + target + "';", encoding="utf-8")
    output = tmp_path / "blocked.tar.gz"
    with pytest.raises((ValueError, FileNotFoundError)):
        build_bundle(output, web_workspace)
    assert not output.exists()
    assert not list(tmp_path.glob(".blocked*"))


@pytest.mark.parametrize(
    "extra",
    [
        "README.md",
        "tests/core.test.cjs",
        "../backend.env",
        "package.json",
        "modules/a.js",
        "app.js",
    ],
)
def test_runtime_manifest_cannot_include_private_files_or_duplicates(
    web_workspace, extra
):
    path = web_workspace / "web/ios/runtime-files.json"
    names = json.loads(path.read_text())
    if extra == "modules/a.js":
        # Syntactically valid but absent assets are rejected before packaging.
        names.append(extra)
        path.write_text(json.dumps(names))
        with pytest.raises(FileNotFoundError):
            validate_runtime(web_workspace)
    else:
        path.write_text(json.dumps([*names, extra]))
        with pytest.raises(ValueError):
            runtime_files(web_workspace)
