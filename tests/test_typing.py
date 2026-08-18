"""Static-typing guard.

pyproject sets ``[tool.mypy] strict = true``; this test turns that contract into
a regression gate so the package can't silently drift back to dozens of type
errors. Invokes the ``mypy`` CLI on PATH (config + strict come from pyproject);
skipped automatically when mypy is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_avalon_package_is_mypy_strict_clean():
    mypy_bin = shutil.which("mypy")
    if mypy_bin is None:
        pytest.skip("mypy is not installed")
    result = subprocess.run(
        [mypy_bin, "avalon"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"mypy reported issues:\n{result.stdout}{result.stderr}"
