"""Fresh-interpreter import checks.

The test session imports ``app`` in one fixed order, which hides circular
imports. ``scripts/bootstrap_admin.py`` imports ``app.crud.audit`` first, and
on a real host that failed with "cannot import name 'JSONType' from partially
initialized module 'app.models.audit'". Each module below is imported first,
alone, in its own interpreter.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

FIRST_IMPORTS = [
    "app.crud.audit",
    "app.models.audit",
    "app.models.client_operation",
    "app.db.base",
    "app.scripts.bootstrap_admin",
    "app.main",
]


@pytest.mark.parametrize("module", FIRST_IMPORTS)
def test_module_imports_first_in_fresh_interpreter(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
