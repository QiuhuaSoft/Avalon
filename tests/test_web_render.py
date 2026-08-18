"""Frontend XSS-regression gate.

Player names are attacker-controlled (any remote player names themselves in the
lobby) and are echoed into the host's privileged game view, so the rendering
code in ``avalon/web/game.js`` must never put a name through ``innerHTML``.

This runs the behavioral node test in ``tests/web/game_render.test.mjs``, which
loads ``game.js`` behind a DOM shim and asserts a ``<img onerror=...>`` name
renders as inert text. Invokes the ``node`` CLI on PATH; skipped automatically
when node is not installed (mirrors ``test_typing.py``'s mypy gate).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_TEST = REPO_ROOT / "tests" / "web" / "game_render.test.mjs"


def test_game_js_does_not_render_names_as_markup():
    node_bin = shutil.which("node")
    if node_bin is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node_bin, "--test", str(NODE_TEST)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"node frontend test failed:\n{result.stdout}{result.stderr}"
