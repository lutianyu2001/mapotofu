"""The parameters of the fonts being built, read from the project's mapotofu.toml.

The project and its directories are mapotofu.project's (the directory holding mapotofu.toml:
$MAPOTOFU_ROOT if set, else the current directory or the nearest one above it holding the file).

The file's tables decide what a change sets going again (see mapotofu.stamps and build.fonts):
[fonts] the glyphs and layout, so the fonts are built anew; [meta] only the names and metadata
(the values listed in META), so the built fonts are finalized again; [hints] and [package] the
second step alone (PACKAGING).
"""

from __future__ import annotations

from dataclasses import dataclass

from .project import BUILD, DATA, PROJECT_FILE, PROJECT_NAME, ROOT, SOURCES  # noqa: F401  (the project's places)
from .project import PROJECT as _project

for _table in ("fonts", "meta", "hints", "package"):
    if _table not in _project:
        raise SystemExit(f"{PROJECT_FILE}: no [{_table}] table")
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
class ItalicCJKSource:
    tag: str
    path: str
    # For a font whose own em box differs, such as a narrow one: scale each glyph by scale_x and
    # scale_y (about the baseline), centre it in `advance` and give it the vertical metrics of
    # Source Han Sans (advance 1000, origin 880).
    advance: int | None = None
    scale_x: float = 1.0
    scale_y: float = 1.0


@dataclass(frozen=True)
class ItalicCJKWeight:
    """One weight of the CJK italics: the sources tried in order, and the lowest
    weight of the fonts it is used from (it holds until the next one's start)."""

    start: int
    sources: tuple[ItalicCJKSource, ...]


def _latin(tag: str) -> LatinSource:
    s = _fonts["latin_sources"][tag]
    return LatinSource(tag, s["file"], tuple(s.get("location", {}).items()), s.get("scale", 1.0))


LATIN = {
    (family, italic): _latin(tags[italic]) for family, tags in _fonts["latin"].items() for italic in ITALIC
}


def _italic_cjk(tag: str, s: str | dict) -> ItalicCJKSource:
    if isinstance(s, str):
        return ItalicCJKSource(tag, s)
    return ItalicCJKSource(tag, s["file"], s.get("advance"), s.get("scale_x", 1.0), s.get("scale_y", 1.0))


# CJK italic sources (a regular-script or slanted font drawn as such), optional: a region (or CJK,
# the shared extension) absent from [fonts.italic_cjk] keeps the ideographs and kana of Source Han
# Sans upright in its italics.
ITALIC_CJK_SOURCES = {tag: _italic_cjk(tag, s) for tag, s in _fonts.get("italic_cjk_sources", {}).items()}
ITALIC_CJK = {
    region: tuple(ItalicCJKWeight(w["from"], tuple(ITALIC_CJK_SOURCES[t] for t in w["sources"])) for w in weights)
    for region, weights in _fonts.get("italic_cjk", {}).items()
    if weights
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
# source's tag, a CJK italic source's tag without its weight letter, "cid" for Source Han
# Sans) -> directory under hints/. Glyphs made here (.notdef) go to HINT_OWN.
HINT_GROUPS = dict(_hints["groups"])
HINT_OWN = _hints["own"]
# Name of the collections (dist/otc): COLLECTION-Regular.otc, COLLECTIONExt-Regular.otc, ...
COLLECTION = _package["collection"]

# Values the second step alone uses: changing them does not build the fonts of the first step
# anew.
PACKAGING = ("HINT_GROUPS", "HINT_OWN", "COLLECTION")
