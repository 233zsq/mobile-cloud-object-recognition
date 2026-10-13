"""Compatibility entry point for legacy 60/20/20 object-group splitting."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml/src"))

from recognition.legacy_data import (  # noqa: E402
    RATIOS as RATIOS,
    REQUIRED_COLUMNS as REQUIRED_COLUMNS,
    SPLIT_ORDER as SPLIT_ORDER,
    assign_groups as assign_groups,
    read_manifest as read_manifest,
    sha256_of as sha256_of,
    split_main,
)


def main() -> int:
    return split_main(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
