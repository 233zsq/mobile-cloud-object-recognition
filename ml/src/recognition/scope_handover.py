"""Add reference examples and stage an experimental CPU package, without approval."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf8",
        newline="\n",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "parent", "verification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    from recognition.inference import LiteRunner
    from recognition.open_set import accepted
    from recognition.preprocessing import preprocess

    if args.output.exists() or (args.release / "examples").exists():
        raise ValueError("Handover already exists; preserve reviewed files")
    runner = LiteRunner(args.release)
    examples = json.loads(
        (args.parent / "examples/manifest.json").read_text(encoding="utf8")
    )
    target = args.release / "examples"
    target.mkdir()
    records = []
    for old in examples:
        record = dict(old)
        for key in ("image", "tensor"):
            source = args.parent / "examples" / old[key]
            if sha(source) != old[key + "_sha256"]:
                raise ValueError("Parent reference changed")
            shutil.copyfile(source, target / old[key])
        tensor = np.fromfile(target / old["tensor"], dtype="<f4").reshape(224, 224, 3)
        result = runner.predict_outputs(tensor)
        image_result = runner.predict_outputs(preprocess(target / old["image"]))
        if (
            np.max(np.abs(result["scores"] - image_result["scores"])) > 0.001
            or abs(result["knownness"] - image_result["knownness"]) > 0.001
        ):
            raise ValueError("Image chain and reference input differ")
        record.update(
            scores=result["scores"].tolist(),
            knownness=result["knownness"],
            predicted_id=int(result["scores"].argmax()),
            recognition_status="accepted"
            if accepted(
                result["scores"][None],
                [result["knownness"]],
                runner.scope_policy["knownness_threshold"],
            )[0]
            else "uncertain",
        )
        records.append(record)
    if len(records) < 20 or any(
        sum(r["category_id"] == i for r in records) < 2 for i in range(10)
    ):
        raise ValueError("Need twenty handover examples, two per class")
    write(target / "manifest.json", records)
    shutil.copyfile(
        args.verification / "report.json", args.release / "independent-runtime.json"
    )
    write(
        args.release / "release-files.json",
        {
            p.relative_to(args.release).as_posix(): sha(p)
            for p in sorted(args.release.rglob("*"))
            if p.is_file() and p.name != "release-files.json"
        },
    )
    args.output.mkdir(parents=True)
    shutil.copytree(args.release, args.output / "release")
    runtime = args.output / "campus_scope_runtime"
    runtime.mkdir()
    (runtime / "__init__.py").write_text("", encoding="utf8")
    for name in ("common.py", "preprocessing.py", "inference.py"):
        shutil.copyfile(ROOT / "ml/src/recognition" / name, runtime / name)
    for name in ("backend_adapter.py", "verify_package.py"):
        shutil.copyfile(ROOT / "deploy/runtime" / name, args.output / name)
    locks = args.output / "locks"
    locks.mkdir()
    shutil.copyfile(
        ROOT / "ml/requirements-wsl-runtime.lock", locks / "linux-py312-runtime.lock"
    )
    shutil.copyfile(
        ROOT / "ml/requirements-windows-runtime.lock", locks / "windows-runtime.lock"
    )
    write(
        args.output / "checksums.json",
        {
            "model_version": runner.metadata["model_version"],
            "files": {
                p.relative_to(args.output).as_posix(): sha(p)
                for p in sorted(args.output.rglob("*"))
                if p.is_file()
            },
        },
    )
    print(
        json.dumps(
            {
                "status": "experimental",
                "approval": "pending_human",
                "examples": len(records),
                "model_sha256": runner.metadata["sha256"],
            }
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
