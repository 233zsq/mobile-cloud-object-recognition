"""Trusted public runtime manifest shared by static publishing and route checks."""

import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
BASE_FILES = {
    "index.html",
    "app.css",
    "app.js",
    "core.js",
    "categories.json",
    "model-contract.json",
    "manifest.webmanifest",
}


def runtime_files(root=ROOT):
    names = json.loads(
        (Path(root) / "web/ios/runtime-files.json").read_text(encoding="utf-8")
    )
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("Expected a public runtime file list")
    if len(names) != len(set(names)) or not BASE_FILES.issubset(names):
        raise ValueError("Duplicate or missing public runtime files")
    for name in names:
        if name not in BASE_FILES and not re.fullmatch(
            r"modules/(?:views/)?[a-z][a-z-]*\.js", name
        ):
            raise ValueError("Unsupported public runtime file: " + name)
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            raise ValueError("Public runtime path escapes the client")
    return frozenset(names)


FILES = runtime_files()


def validate_runtime(root=ROOT):
    """Check the complete native-module graph before a bundle can be created."""
    root = Path(root)
    client = (root / "web/ios").resolve()
    files = runtime_files(root)
    content = {}
    for name in sorted(files):
        path = (client / name).resolve()
        if not path.is_relative_to(client):
            raise ValueError("Public source escapes the client: " + name)
        content[name] = path.read_bytes()
    for name, data in content.items():
        text = data.decode("utf-8") if name.endswith((".html", ".js")) else ""
        if name.endswith(".html"):
            references = re.findall(r'(?:src|href)=[\'"]([^\'"]+)[\'"]', text)
            references = [
                value
                for value in references
                if not value.startswith(("/", "#")) and "://" not in value
            ]
        elif name.endswith(".js"):
            references = re.findall(
                r'(?:\bfrom\s*|\bimport\s*)[\'"]([^\'"]+)[\'"]', text
            )
        else:
            references = []
        for reference in references:
            path = (client / PurePosixPath(name).parent / reference).resolve()
            if (
                not path.is_relative_to(client)
                or path.relative_to(client).as_posix() not in files
            ):
                raise ValueError(
                    "Undeclared public dependency: " + name + " -> " + reference
                )
    return content
