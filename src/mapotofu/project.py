"""The font project: the directory holding mapotofu.toml, and that file as it is written.

The project is $MAPOTOFU_ROOT if set, else the current directory or the nearest one above it
holding the file. Its sources/, data/, hints/, build/ and dist/ sit next to the file. The
variable is set for processes started from here, so that workers and subprocesses read the same
project from any directory.

Nothing here looks into the file's tables: mapotofu.config reads those of the fonts it builds,
while fetching the sources (mapotofu.fetch) and programs that keep tables of their own in the
file need only the place and the parsed file (PROJECT).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

PROJECT_NAME = "mapotofu.toml"


def _root() -> Path:
    if env := os.environ.get("MAPOTOFU_ROOT"):
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        if (d / PROJECT_NAME).is_file():
            return d
    raise SystemExit(f"no {PROJECT_NAME} in {here} or above it; run in a font project or set MAPOTOFU_ROOT")


ROOT = _root()
os.environ["MAPOTOFU_ROOT"] = str(ROOT)
PROJECT_FILE = ROOT / PROJECT_NAME
SOURCES = ROOT / "sources"
DATA = ROOT / "data"
BUILD = ROOT / "build"

try:
    PROJECT = tomllib.loads(PROJECT_FILE.read_text())
except (OSError, tomllib.TOMLDecodeError) as ex:
    raise SystemExit(f"{PROJECT_FILE}: {ex}") from None
