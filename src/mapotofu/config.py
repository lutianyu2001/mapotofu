"""The parameters of the fonts being built, read from the project's mapotofu.toml.

The project is the directory holding mapotofu.toml: $MAPOTOFU_ROOT if set, else the current
directory or the nearest one above it holding the file. Its sources/, data/, hints/, build/ and
dist/ sit next to the file. The variable is set for processes started from here, so that workers
and subprocesses read the same project from any directory.

The file's tables decide what a change sets going again (see mapotofu.stamps and build.fonts):
[fonts] the glyphs and layout, so the fonts are built anew; [meta] only the names and metadata
(the values listed in META), so the built fonts are finalized again; [hints] and [package] the
second step alone (PACKAGING).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
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
    _project = tomllib.loads(PROJECT_FILE.read_text())
except (OSError, tomllib.TOMLDecodeError) as ex:
    raise SystemExit(f"{PROJECT_FILE}: {ex}") from None
_fonts, _meta = _project["fonts"], _project["meta"]
_hints, _package = _project["hints"], _project["package"]

ITALIC = (False, True)
REGIONS = tuple(_fonts["regions"])
FAMILIES = tuple(_fonts["families"])

# Weight axis and masters (see the project file).
AXIS_MIN, AXIS_DEFAULT, AXIS_MAX = (_fonts["axis"][k] for k in ("min", "default", "max"))
MASTERS = tuple(_fonts["masters"])
# Weight of the fonts -> Source Han Sans weight, linear in between.
CJK_WEIGHT_MAP = tuple(tuple(pair) for pair in _fonts["cjk_weights"])

SHS = {r: v["file"] for r, v in _fonts["cjk"].items()}
OT_LANG = {r: v["language"] for r, v in _fonts["cjk"].items()}


@dataclass(frozen=True)
class LatinSource:
    tag: str  # glyph name prefix
    path: str
    location: tuple[tuple[str, float], ...] = ()  # fixed coordinates of other axes
    scale: float = 1.0


@dataclass(frozen=True)
class KaiSource:
    tag: str
    path: str


@dataclass(frozen=True)
class KaiWeight:
    """One regular-script weight used in italics: the sources tried in order, and the lowest
    weight of the fonts it is used from (it holds until the next one's start)."""

    start: int
    sources: tuple[KaiSource, ...]


def _latin(tag: str) -> LatinSource:
    s = _fonts["latin_sources"][tag]
    return LatinSource(tag, s["file"], tuple(s.get("location", {}).items()), s.get("scale", 1.0))


LATIN = {
    (family, italic): _latin(tags[italic]) for family, tags in _fonts["latin"].items() for italic in ITALIC
}
KAI_SOURCES = {tag: KaiSource(tag, path) for tag, path in _fonts["kai_sources"].items()}
KAI = {
    region: tuple(KaiWeight(w["from"], tuple(KAI_SOURCES[t] for t in w["sources"])) for w in weights)
    for region, weights in _fonts["kai"].items()
}

VERSION = _meta["version"]
STATIC_WEIGHTS = {name: w["value"] for name, w in _meta["weights"].items()}
WEIGHT_CLASS = {name: w["class"] for name, w in _meta["weights"].items()}
WIN_LANG = {r: v["windows_language"] for r, v in _meta["regions"].items()}
CODEPAGE_BIT = {r: v["code_page_bit"] for r, v in _meta["regions"].items()}
FAMILY_NAMES = {family: {r: tuple(n) for r, n in names.items()} for family, names in _meta["names"].items()}
EXT_CJK_NAMES = (_meta["ext_cjk"]["name"], dict(_meta["ext_cjk"]["local"]))
LOCAL_STYLE = {r: dict(styles) for r, styles in _meta["styles"].items()}
DESIGNER = _meta["designer"]
COPYRIGHT_OWN = _meta["copyright"]
LICENSE = _meta["license"]
LICENSE_URL = _meta["license_url"]
VENDOR = _meta["vendor"]

# Values only the metadata uses (meta.py): changing them sets the metadata of the built fonts
# again instead of building them anew (see build.fonts).
META = (
    "VERSION", "STATIC_WEIGHTS", "WEIGHT_CLASS", "WIN_LANG", "CODEPAGE_BIT", "FAMILY_NAMES",
    "EXT_CJK_NAMES", "LOCAL_STYLE", "DESIGNER", "COPYRIGHT_OWN", "LICENSE", "LICENSE_URL", "VENDOR",
)

# Where the hints of glyphs from each source are kept (hintcache): glyph name prefix (a Latin
# source's tag, a regular-script source's tag without its weight letter, "cid" for Source Han
# Sans) -> directory under hints/. Glyphs made here (.notdef) go to HINT_OWN.
HINT_GROUPS = dict(_hints["groups"])
HINT_OWN = _hints["own"]
# Name of the collections (dist/otc): COLLECTION-Regular.otc, COLLECTIONExt-Regular.otc, ...
COLLECTION = _package["collection"]

# Values the second step alone uses: changing them does not build the fonts of the first step
# anew.
PACKAGING = ("HINT_GROUPS", "HINT_OWN", "COLLECTION")
