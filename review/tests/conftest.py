from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campus_review import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'SECRET_KEY': 'test-' * 10, 'DATA_DIR': str(tmp_path),
                       'SESSION_COOKIE_SECURE': False})
