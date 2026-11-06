"""The tests read the configuration of tests/project, a font project with nothing built."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MAPOTOFU_ROOT", str(Path(__file__).resolve().parent / "project"))
