"""Compatibility entry point for legacy 11-column collection manifest checks."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml/src"))

from recognition.legacy_data import (  # noqa: E402
    REQUIRED_COLUMNS as REQUIRED_COLUMNS,
    VALID_CATEGORY_IDS as VALID_CATEGORY_IDS,
    VALID_REVIEW as VALID_REVIEW,
    VALID_SPLITS as VALID_SPLITS,
    check_main,
    read_manifest as read_manifest,
    sha256_of as sha256_of,
    sharpness as sharpness,
    write_manifest_atomic as write_manifest_atomic,
)


def main() -> int:
    return check_main(Path(__file__).resolve().parents[1], sharpness=sharpness)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
