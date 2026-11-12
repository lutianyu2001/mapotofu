"""Split the ideographs of Source Han Sans into the main fonts and the two extensions (PLAN 3)."""

from __future__ import annotations

import functools
from dataclasses import dataclass

from fontTools.ttLib import TTFont

from .charsets import common, is_tiered
from .config import REGIONS, SHS, SOURCES


@functools.cache
def shs_cmap(region: str) -> dict[int, int]:
    """Code point -> glyph ID (Source Han Sans glyph IDs are its CIDs, the same in every region)."""
    font = TTFont(SOURCES / SHS[region], lazy=True)
    order = {name: gid for gid, name in enumerate(font.getGlyphOrder())}
    return {cp: order[name] for cp, name in font.getBestCmap().items()}


@dataclass(frozen=True)
class Tiers:
    main: dict[str, frozenset[int]]  # region -> common ideographs it has
    ext: dict[str, frozenset[int]]  # region -> rare ideographs drawn differently elsewhere
    shared: frozenset[int]  # rare everywhere and drawn the same everywhere


@functools.cache
def tiers() -> Tiers:
    ideo = {r: {cp for cp in shs_cmap(r) if is_tiered(cp)} for r in REGIONS}
    main = {r: frozenset(ideo[r] & common(r)) for r in REGIONS}
    rare = {r: ideo[r] - main[r] for r in REGIONS}
    shared = frozenset(
        cp
        for cp in set.intersection(*rare.values())
        if len({shs_cmap(r)[cp] for r in REGIONS}) == 1
    )
    ext = {r: frozenset(rare[r] - shared) for r in REGIONS}
    return Tiers(main, ext, shared)


if __name__ == "__main__":
    t = tiers()
    for r in REGIONS:
        print(r, "main", len(t.main[r]), "ext", len(t.ext[r]))
    print("shared", len(t.shared))
