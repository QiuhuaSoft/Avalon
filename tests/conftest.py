"""Test configuration.

This module runs before any test module imports the avalon package, which
matters because avalon.config reads the environment at import time. Heuristic
bot mode keeps tests free of MLX model loading, and the temporary database
isolates test runs from any local dev database.
"""

import os
import tempfile
from pathlib import Path

os.environ["AVALON_BOT_MODE"] = "heuristic"
os.environ["AVALON_DB"] = str(Path(tempfile.mkdtemp(prefix="avalon-test-")) / "events.sqlite")
