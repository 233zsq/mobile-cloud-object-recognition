"""Compatibility entrypoint; the shared renderer keeps this report profile."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml/src"))
from recognition.reports import main


if __name__ == "__main__":
    main(profile="expanded-cpu")
