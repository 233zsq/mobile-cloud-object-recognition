"""Photo review application; training runs in a separate process."""
from .factory import create_app
from .paths import ROOT

__all__ = ["ROOT", "create_app"]
