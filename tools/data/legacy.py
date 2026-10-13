"""Compatibility import; collection business rules live in recognition.legacy_data."""

from recognition import legacy_data as implementation
import sys

sys.modules[__name__] = implementation
