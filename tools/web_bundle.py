"""Build the exact public /ios runtime bundle; no tests, credentials or tooling files."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

from deploy.ios_assets import ROOT, validate_runtime


def build_bundle(output, root=ROOT):
    output = Path(output)
    if output.exists():
        raise ValueError("Bundle already exists; choose a new output file")
    content = validate_runtime(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output.parent, prefix="." + output.name + ".", delete=False
        ) as stream:
            temporary = Path(stream.name)
            with gzip.GzipFile(
                fileobj=stream, filename="", mode="wb", mtime=0
            ) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name, data in sorted(content.items()):
                        item = tarfile.TarInfo(name)
                        item.size = len(data)
                        item.mode = 0o644
                        archive.addfile(item, io.BytesIO(data))
            stream.flush()
            os.fsync(stream.fileno())
        # Windows rename and POSIX link both atomically refuse an existing destination.
        if os.name == "nt":
            temporary.rename(output)
        else:
            os.link(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return {
        "path": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(content.items())
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(build_bundle(args.output, args.root), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    raise SystemExit(main())
