"""Byte identities and failed/concurrent writes across both manifest adapters."""

import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from recognition import common, manifest_io


def test_formal_reader_preserves_bom_extension_columns_and_whitespace(tmp_path):
    source = tmp_path / "source.csv"
    source.write_bytes(b"\xef\xbb\xbfsample_id,note\r\n sample-1 , keep me \r\n")
    assert common.read_csv(source) == [{"sample_id": " sample-1 ", "note": " keep me "}]
    with pytest.raises(ValueError, match="表头"):
        manifest_io.read_legacy_manifest(source)
    output = tmp_path / "formal.csv"
    common.write_csv(output, common.read_csv(source))
    expected = (
        ",".join(manifest_io.FIELDS)
        + "\r\n"
        + " sample-1 ,"
        + "," * (len(manifest_io.FIELDS) - 2)
        + "\r\n"
    )
    assert output.read_bytes() == expected.encode()


@pytest.mark.parametrize("legacy", [False, True])
def test_failed_csv_serialization_preserves_original_and_cleans_temporary_file(
    tmp_path, monkeypatch, legacy
):
    destination = tmp_path / "manifest.csv"
    destination.write_bytes(b"previous frozen bytes\r\n")
    before = destination.read_bytes()

    def interrupted(writer, rows):
        writer.writerow(next(iter(rows)))
        raise ValueError("serialization interrupted")

    monkeypatch.setattr(csv.DictWriter, "writerows", interrupted)
    writer = manifest_io.write_legacy_manifest if legacy else common.write_csv
    with pytest.raises(ValueError, match="interrupted"):
        writer(destination, [{"sample_id": "new"}])
    assert destination.read_bytes() == before
    assert list(tmp_path.iterdir()) == [destination]


def test_concurrent_writes_use_independent_temporary_files(tmp_path):
    destination = tmp_path / "state.json"
    barrier = Barrier(2)

    def publish(content):
        def serialize(stream):
            stream.write(content)
            barrier.wait(timeout=5)

        manifest_io.atomic_write(destination, serialize)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(publish, ["first完整状态", "second完整状态"]))
    assert destination.read_text(encoding="utf-8") in [
        "first完整状态",
        "second完整状态",
    ]
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize(
    "seed,pending,name",
    [(42, False, "seed42"), (43, False, "seed43"), (42, True, "seed42-pending")],
)
def test_legacy_frozen_output_matches_pre_refactor_fixture(
    tmp_path, monkeypatch, seed, pending, name
):
    import json
    import sys
    from tools.data.legacy import split_main

    fixture = Path(__file__).resolve().parents[2] / "tests/fixtures/data-tools"
    relative = "tests/fixtures/data-tools/source.csv"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_bytes((fixture / "source.csv").read_bytes())
    original = source.read_bytes()
    argv = [
        "split_dataset.py",
        relative,
        "--data-version",
        "compat-fixture",
        "--seed",
        str(seed),
    ]
    if pending:
        argv.append("--include-pending")
    monkeypatch.setattr(sys, "argv", argv)
    assert split_main(tmp_path) == 0
    output = tmp_path / "data/splits/compat-fixture"
    for split in ["train", "validation", "test"]:
        assert (output / (split + ".csv")).read_bytes() == (
            fixture / name / (split + ".csv")
        ).read_bytes()
    info = json.loads((output / "split-info.json").read_text(encoding="utf-8"))
    for value in info["files"].values():
        value["path"] = value["path"].replace("\\", "/")
    assert info == json.loads(
        (fixture / name / "split-info.json").read_text(encoding="utf-8")
    )
    assert source.read_bytes() == original
    frozen = {p.name: p.read_bytes() for p in output.iterdir()}
    assert split_main(tmp_path) == 1
    assert frozen == {p.name: p.read_bytes() for p in output.iterdir()}
