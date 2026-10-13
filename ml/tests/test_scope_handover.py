"""The delivered CPU adapter must import without the training source tree."""
import os
import subprocess
import sys

from recognition.scope_handover import copy_cpu_runtime


def test_cpu_payload_imports_and_reads_manifests_as_a_standalone_package(tmp_path):
    copy_cpu_runtime(tmp_path)
    code = """
import sys
from pathlib import Path
from backend_adapter import CpuModelService
from campus_scope_runtime.common import read_json, write_json, digest
assert callable(CpuModelService)
assert 'recognition' not in sys.modules
assert 'tensorflow' not in sys.modules and 'keras' not in sys.modules
path = Path('probe.json')
write_json(path, {'model_version': 'synthetic-boundary-check'})
assert read_json(path) == {'model_version': 'synthetic-boundary-check'}
assert len(digest(path)) == 64
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
