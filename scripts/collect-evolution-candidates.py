"""Compatibility CLI; implementation: recognition.collect_increment."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ml/src"))

from recognition.collect_increment import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
