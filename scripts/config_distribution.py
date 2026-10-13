"""Compatibility import for tools.config.distribution; shared module identity preserves patches."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.config import distribution as implementation  # noqa: E402

sys.modules[__name__] = implementation
