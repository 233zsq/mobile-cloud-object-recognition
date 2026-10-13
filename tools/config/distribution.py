"""Versioned configuration distribution using pinned public source bytes."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[2]
GROUPS = ("legacy", "database", "android", "backend", "web")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def version(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value
    ):
        raise ValueError("Invalid version identifier")
    return value


def repo_path(root, name):
    if (
        not isinstance(name, str)
        or "\\" in name
        or Path(name).is_absolute()
        or ".." in Path(name).parts
    ):
        raise ValueError("Expected a repository-relative path")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Configuration path escapes the repository")
    return path


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Catalog:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.index = json.loads(
            (self.root / "shared/config-distribution.json").read_bytes()
        )
        require(
            type(self.index.get("schema_version")) is int
            and self.index["schema_version"] == 1,
            "Unsupported distribution schema",
        )
        require(
            set(self.index.get("bindings", {})) == set(GROUPS),
            "Expected all five distribution bindings",
        )
        self.categories, self.models, self.policies = {}, {}, {}
        for key, entry in self.index["categories"].items():
            version(key)
            data = self.pinned(entry["file"], entry["sha256"])
            category = json.loads(data)
            items = category["categories"]
            require(
                category.get("status") == "frozen"
                and category.get("category_version") == key,
                "Category version/status mismatch: " + key,
            )
            require(
                all(type(c["id"]) is int for c in items)
                and [c["id"] for c in items] == list(range(10))
                and all(
                    isinstance(c["label_key"], str)
                    and re.fullmatch(r"[a-z][a-z0-9_]*", c["label_key"])
                    for c in items
                )
                and len({c["label_key"] for c in items}) == 10,
                "Category label order mismatch: " + key,
            )
            self.categories[key] = (category, data)
        reference = self.categories[self.index["label_order_category_version"]][0]
        self.labels = tuple(c["label_key"] for c in reference["categories"])
        for key, (category, _) in self.categories.items():
            require(
                tuple(c["label_key"] for c in category["categories"]) == self.labels,
                "Category label order mismatch: " + key,
            )
        for key, entry in self.index["models"].items():
            version(key)
            meta = json.loads(
                self.pinned(entry["metadata_file"], entry["metadata_sha256"])
            )
            labels = self.pinned(entry["labels_file"], entry["labels_sha256"])
            require(
                meta.get("status") == "frozen" and meta.get("model_version") == key,
                "Model version/status mismatch: " + key,
            )
            category = self.categories[meta["category_version"]][0]
            require(
                labels.decode("utf-8").splitlines() == list(self.labels)
                and all(type(c["id"]) is int for c in meta["categories"])
                and meta["categories"] == category["categories"]
                and sha256(labels) == meta["labels_sha256"],
                "Model labels/category identity mismatch: " + key,
            )
            require(
                isinstance(meta.get("sha256"), str)
                and re.fullmatch("[a-f0-9]{64}", meta["sha256"])
                and type(meta.get("low_confidence_threshold")) in (int, float)
                and math.isfinite(meta["low_confidence_threshold"])
                and 0 <= meta["low_confidence_threshold"] <= 1,
                "Invalid model identity/threshold: " + key,
            )
            self.models[key] = (meta, labels)
        for key, entry in self.index["policies"].items():
            version(key)
            data = self.pinned(entry["file"], entry["sha256"])
            checksum = repo_path(self.root, entry["checksum_file"]).read_bytes()
            require(
                checksum.decode("ascii").strip() == sha256(data),
                "Policy checksum mismatch: " + key,
            )
            policy = json.loads(data)
            meta = self.models[policy["model_version"]][0]
            require(
                policy.get("policy_version") == key
                and policy.get("status") in ("experimental", "frozen"),
                "Policy version/status mismatch: " + key,
            )
            identity = {
                "model_version": meta["model_version"],
                "model_sha256": meta["sha256"],
                "labels_sha256": meta["labels_sha256"],
                "category_version": meta["category_version"],
                "preprocessing_version": meta["input"]["version"],
            }
            require(
                all(policy.get(k) == v for k, v in identity.items()),
                "Policy/model identity mismatch: " + key,
            )
            thresholds = ["confidence_threshold", "margin_threshold"]
            if policy.get("rule") == "learned_knownness_v1":
                require(
                    key == "scope-knownness-v1"
                    and meta.get("scope_output", {}).get("interpretation")
                    == "knownness",
                    "Learned policy requires the matching model output",
                )
                thresholds.append("knownness_threshold")
            else:
                require(
                    policy.get("rule") == "msp_margin_v1" and key == "scope-basic-v1",
                    "Unsupported scope policy rule",
                )
            require(
                all(
                    type(policy.get(k)) in (int, float)
                    and math.isfinite(policy[k])
                    and 0 <= policy[k] <= 1
                    for k in thresholds
                ),
                "Invalid policy thresholds: " + key,
            )
            if meta.get("scope_policy_file"):
                filename = meta["scope_policy_file"]
                require(
                    isinstance(filename, str)
                    and re.fullmatch(r"[A-Za-z0-9._-]+", filename),
                    "Invalid released policy filename",
                )
                published = repo_path(
                    self.root,
                    str(
                        Path(
                            self.index["models"][policy["model_version"]][
                                "metadata_file"
                            ]
                        ).parent
                        / filename
                    ).replace("\\", "/"),
                )
                require(
                    meta.get("scope_policy_sha256") == sha256(data)
                    and published.read_bytes() == data,
                    "Released policy differs from the shared archive: " + key,
                )
            self.policies[key] = (policy, data, checksum)
        for key, entry in self.index["models"].items():
            self.policy_for(key, entry.get("policy_version"))

    def pinned(self, filename, expected):
        require(
            isinstance(expected, str) and re.fullmatch("[a-f0-9]{64}", expected),
            "Invalid source SHA-256",
        )
        data = repo_path(self.root, filename).read_bytes()
        require(sha256(data) == expected, "Source SHA-256 mismatch: " + filename)
        return data

    def policy_for(self, model_version, policy_version):
        if policy_version is None:
            require(
                not self.models[model_version][0].get("scope_output"),
                "Model requires its learned scope policy",
            )
            return None
        policy = self.policies[policy_version]
        require(
            policy[0]["model_version"] == model_version,
            "Selected policy belongs to another model",
        )
        return policy

    def web_contract(self, model_version, policy_version):
        meta, _ = self.models[model_version]
        policy = self.policy_for(model_version, policy_version)
        contract = {
            "schema_version": 1,
            "model_version": model_version,
            "model_sha256": meta["sha256"],
            "category_version": meta["category_version"],
            "low_confidence_threshold": meta["low_confidence_threshold"],
            "threshold_status": meta["threshold_status"],
            "labels_sha256": meta["labels_sha256"],
            "labels": list(self.labels),
        }
        if policy is not None:
            value, data, _ = policy
            newline = "CRLF" if b"\r\n" in data else "LF"
            reconstructed = (
                json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            if newline == "CRLF":
                reconstructed = reconstructed.replace(b"\n", b"\r\n")
            require(
                reconstructed == data,
                "Embedded policy cannot preserve its original bytes",
            )
            contract.update(
                scope_policy_sha256=sha256(data),
                scope_policy_newline=newline,
                scope_policy=value,
            )
        else:
            contract["scope_policy"] = None
        # Preserve the existing contract layout: flat label array, indented policy object.
        lines = ["{"]
        for key, value in contract.items():
            encoded = json.dumps(
                value, ensure_ascii=False, indent=2 if isinstance(value, dict) else None
            ).splitlines()
            lines.append("  " + json.dumps(key) + ": " + encoded[0])
            lines.extend("  " + line for line in encoded[1:])
            lines[-1] += ","
        lines[-1] = lines[-1][:-1]
        return ("\n".join([*lines, "}", ""])).encode("utf-8")

    def targets(self, groups=GROUPS):
        result, immutable = {}, set()
        for group in groups:
            binding = self.index["bindings"][group]
            if group in ("legacy", "database", "android"):
                key = binding["category_version"]
                data = self.categories[key][1]
                names = {
                    "legacy": "shared/categories.json",
                    "database": "database/seeds/categories." + key + ".json",
                    "android": "android/app/src/main/assets/categories.json",
                }
                result[names[group]] = data
                if group in ("legacy", "database"):
                    immutable.add(names[group])
            if group in ("android", "backend"):
                key = binding["policy_version"]
                policy, data, checksum = self.policies[key]
                if group == "android":
                    require(
                        policy["category_version"] == binding["category_version"],
                        "Android category/policy version mismatch",
                    )
                    result["android/app/src/main/assets/scope/scope-policy.json"] = data
                    result["android/app/src/main/assets/scope/scope-policy.sha256"] = (
                        checksum
                    )
                else:
                    result["backend/policies/" + key + ".json"] = data
            if group == "web":
                key = binding["model_version"]
                result["web/ios/categories.json"] = self.categories[
                    self.models[key][0]["category_version"]
                ][1]
                result["web/ios/model-contract.json"] = self.web_contract(
                    key, binding.get("policy_version")
                )
        return result, immutable

    def check(self, groups=GROUPS):
        expected, _ = self.targets(groups)
        return [
            {
                "path": name,
                "expected_sha256": sha256(data),
                "actual_sha256": sha256(path.read_bytes()) if path.is_file() else None,
            }
            for name, data in expected.items()
            if not (path := repo_path(self.root, name)).is_file()
            or path.read_bytes() != data
        ]

    def generate(self, groups=GROUPS):
        # Validate every binding and frozen target before touching any mutable copy.
        all_targets, immutable = self.targets()
        for name in immutable:
            path = repo_path(self.root, name)
            require(
                not path.exists() or path.read_bytes() == all_targets[name],
                "Immutable compatibility file differs: " + name,
            )
        expected, _ = self.targets(groups)
        changes = {
            repo_path(self.root, name): data
            for name, data in expected.items()
            if not repo_path(self.root, name).is_file()
            or repo_path(self.root, name).read_bytes() != data
        }
        write_batch(changes)
        return [str(path.relative_to(self.root)).replace("\\", "/") for path in changes]

    def export(self, output, category_version, model_version=None, policy_version=None):
        version(category_version)
        category, data = self.categories[category_version]
        files = {
            "categories.json": data,
            "labels.txt": (
                "\n".join(item["label_key"] for item in category["categories"]) + "\n"
            ).encode("utf-8"),
        }
        selected = None
        if model_version is not None:
            version(model_version)
            meta, labels = self.models[model_version]
            require(
                meta["category_version"] == category_version,
                "Export category/model version mismatch",
            )
            selected = (
                policy_version
                if policy_version is not None
                else self.index["models"][model_version].get("policy_version")
            )
            policy = self.policy_for(model_version, selected)
            files.update(
                {
                    "labels.txt": labels,
                    "model-contract.json": self.web_contract(model_version, selected),
                }
            )
            if policy is not None:
                files.update(
                    {"scope-policy.json": policy[1], "scope-policy.sha256": policy[2]}
                )
        else:
            require(policy_version is None, "A policy export requires --model-version")
        receipt = {
            "schema_version": 1,
            "category_version": category["category_version"],
            "category_sha256": sha256(data),
            "model_version": model_version,
            "policy_version": selected,
            "files": {name: sha256(content) for name, content in files.items()},
        }
        files["config-receipt.json"] = (
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        try:
            write_batch({output / name: content for name, content in files.items()})
        except BaseException:
            output.rmdir()
            raise
        return receipt


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix="." + path.name + ".", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            temporary.chmod(path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_batch(changes):
    previous = {path: path.read_bytes() if path.exists() else None for path in changes}
    applied = []
    try:
        for path, content in changes.items():
            atomic_write(path, content)
            applied.append(path)
    except BaseException:
        for path in reversed(applied):
            if previous[path] is None:
                path.unlink()
            else:
                atomic_write(path, previous[path])
        raise
