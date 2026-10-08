"""Regression tests for manifest backfill and grouped dataset freezing (stdlib only)."""

import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import check_manifest
import split_dataset


class DataScriptsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT, prefix="test-data-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.csv"

    def row(self, sample_id="sample-1", object_id="cup-01", **fields):
        row = dict.fromkeys(check_manifest.REQUIRED_COLUMNS, "")
        row.update(
            sample_id=sample_id, image_path=f"images/{sample_id}.jpg",
            category_id="0", object_id=object_id, session_id="session-1",
            collector="collector-a", captured_at="2026-10-08",
            review_status="approved",
        )
        row.update(fields)
        return row

    def write_manifest(self, rows, columns=None):
        with self.manifest.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=columns or check_manifest.REQUIRED_COLUMNS,
            )
            writer.writeheader()
            writer.writerows(rows)

    def make_image(self, row):
        path = self.root / row["image_path"].strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image fixture: " + row["sample_id"].encode())
        return path

    def run_script(self, module, *args):
        output = io.StringIO()
        with patch.object(module, "__file__", str(self.root / "scripts" / "cli.py")), \
                patch.object(sys, "argv", ["cli.py", "manifest.csv", *args]), \
                redirect_stdout(output):
            code = module.main()
        return code, output.getvalue()

    def backfill(self):
        # These cases exercise real file hashing/writing; image decoding is separate.
        with patch.object(check_manifest, "sharpness", return_value=100.0):
            return self.run_script(check_manifest, "--check-files", "--fill-sha256")

    def assert_no_temporary_files(self):
        self.assertEqual({path.name for path in self.root.iterdir()},
                         {"manifest.csv", "images"})

    def test_extra_header_does_not_truncate_manifest(self):
        row = self.row(note="collection note")
        self.make_image(row)
        self.write_manifest([row], check_manifest.REQUIRED_COLUMNS + ["note"])
        original = self.manifest.read_bytes()

        code, output = self.backfill()

        self.assertEqual(code, 1)
        self.assertIn("表头", output)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_invalid_row_width_does_not_change_manifest(self):
        row = self.row()
        self.make_image(row)
        for delta in (-1, 1):
            with self.subTest(delta=delta):
                values = [row[column] for column in check_manifest.REQUIRED_COLUMNS]
                values = values[:-1] if delta < 0 else values + ["extra"]
                with self.manifest.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(check_manifest.REQUIRED_COLUMNS)
                    writer.writerow(values)
                original = self.manifest.read_bytes()

                code, _ = self.backfill()

                self.assertEqual(code, 1)
                self.assertEqual(self.manifest.read_bytes(), original)

    def test_validation_errors_prevent_backfill(self):
        row = self.row(category_id="99")
        self.make_image(row)
        self.write_manifest([row])
        original = self.manifest.read_bytes()

        code, _ = self.backfill()

        self.assertEqual(code, 1)
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_successful_backfill_preserves_all_rows_and_hashes(self):
        rows = [self.row(), self.row("sample-2", "cup-02")]
        hashes = [hashlib.sha256(self.make_image(row).read_bytes()).hexdigest()
                  for row in rows]
        self.write_manifest(rows)

        code, _ = self.backfill()

        self.assertEqual(code, 0)
        with self.manifest.open(newline="", encoding="utf-8") as stream:
            saved = list(csv.DictReader(stream))
        self.assertEqual(saved, [dict(row, image_sha256=digest)
                                 for row, digest in zip(rows, hashes)])
        self.assert_no_temporary_files()

    def test_serialization_failure_preserves_original_and_cleans_temp(self):
        row = self.row()
        self.make_image(row)
        self.write_manifest([row])
        original = self.manifest.read_bytes()

        with patch.object(csv.DictWriter, "writerows", side_effect=ValueError("write failed")):
            code, output = self.backfill()

        self.assertEqual(code, 1)
        self.assertIn("write failed", output)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_replace_failure_preserves_original_and_cleans_temp(self):
        row = self.row()
        self.make_image(row)
        self.write_manifest([row])
        original = self.manifest.read_bytes()

        with patch.object(Path, "replace", side_effect=PermissionError("replace failed")):
            code, output = self.backfill()

        self.assertEqual(code, 1)
        self.assertIn("replace failed", output)
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assert_no_temporary_files()

    def test_checker_counts_normalized_object_ids(self):
        self.write_manifest([
            self.row(f"sample-{i}", object_id)
            for i, object_id in enumerate(["cup-01", "cup-01 ", "cup-02", "cup-03", "cup-04"])
        ])

        code, output = self.run_script(check_manifest)

        self.assertEqual(code, 0)
        self.assertIn("5 张, 4 件实物", output)

    def test_whitespace_variants_stay_in_one_split(self):
        for padded_category in ("0", " 0 "):
            with self.subTest(category_id=padded_category):
                rows = [self.row(f"sample-{i}", object_id)
                        for i, object_id in enumerate(
                            ["cup-01", "cup-01 ", "cup-02", "cup-03", "cup-04"])]
                rows[1]["category_id"] = padded_category
                if padded_category != "0":
                    rows[1]["review_status"] = " approved "
                self.write_manifest(rows)
                original = self.manifest.read_bytes()
                version = "v1" if padded_category == "0" else "v2"

                code, _ = self.run_script(split_dataset, "--data-version", version)

                self.assertEqual(code, 0)
                objects = {}
                samples = set()
                out_dir = self.root / "data" / "splits" / version
                for split in split_dataset.SPLIT_ORDER:
                    with (out_dir / f"{split}.csv").open(newline="", encoding="utf-8") as stream:
                        for row in csv.DictReader(stream):
                            self.assertEqual(row["object_id"], row["object_id"].strip())
                            self.assertEqual(row["category_id"], "0")
                            objects.setdefault(row["object_id"], set()).add(split)
                            samples.add(row["sample_id"])
                self.assertEqual(samples, {row["sample_id"] for row in rows})
                self.assertTrue(all(len(splits) == 1 for splits in objects.values()))
                self.assertEqual(len(objects), 4)
                self.assertEqual(self.manifest.read_bytes(), original)

    def test_invalid_manifest_does_not_create_frozen_version(self):
        self.write_manifest([self.row(note="extra")], check_manifest.REQUIRED_COLUMNS + ["note"])

        code, _ = self.run_script(split_dataset, "--data-version", "invalid")

        self.assertEqual(code, 1)
        self.assertFalse((self.root / "data" / "splits" / "invalid").exists())

    def test_frozen_version_and_hashes_remain_unchanged(self):
        self.write_manifest([self.row(f"sample-{i}", f"cup-{i}") for i in range(5)])
        code, _ = self.run_script(split_dataset, "--data-version", "v1")
        self.assertEqual(code, 0)
        out_dir = self.root / "data" / "splits" / "v1"
        original = {path.name: path.read_bytes() for path in out_dir.iterdir()}
        info = json.loads(original["split-info.json"])
        for split in split_dataset.SPLIT_ORDER:
            self.assertEqual(info["files"][split]["sha256"],
                             hashlib.sha256(original[f"{split}.csv"]).hexdigest())

        code, _ = self.run_script(split_dataset, "--data-version", "v1", "--seed", "99")

        self.assertEqual(code, 1)
        self.assertEqual({path.name: path.read_bytes() for path in out_dir.iterdir()}, original)


if __name__ == "__main__":
    unittest.main()
