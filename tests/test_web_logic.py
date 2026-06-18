"""Frontend logic gate for the proposal-history matrix.

``avalon/web/game.js`` reconstructs the per-proposal matrix from the redacted
public event stream (``buildProposalRecords``), labels each mission verdict
(``missionSummary``), and describes the proposal/hammer countdown
(``hammerText``). That fold has to track the way ``public_events()`` withholds
team ballots until a proposal resolves and drops quest ballots entirely, so it
gets behavioral coverage rather than only the XSS-rendering gate.

This runs the node test in ``tests/web/proposal_records.test.mjs``, which loads
``game.js`` behind a DOM shim and exercises those pure functions directly.
Invokes the ``node`` CLI on PATH; skipped when node is absent (mirrors
``test_web_render.py`` and ``test_typing.py``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE_TEST = REPO_ROOT / "tests" / "web" / "proposal_records.test.mjs"


def test_proposal_matrix_reconstruction_is_correct():
    node_bin = shutil.which("node")
    if node_bin is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node_bin, "--test", str(NODE_TEST)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"node frontend test failed:\n{result.stdout}{result.stderr}"
