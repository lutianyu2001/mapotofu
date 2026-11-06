"""Standalone fonts cut from pool-backed ones."""

from __future__ import annotations

import io
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

from . import layout, stamps


def bake_rvrn(font: TTFont) -> None:
    """In a static italic, put the regular-script weight chosen by rvrn into the cmap."""
    if "GSUB" not in font:
        return
    gsub = font["GSUB"].table
    if "rvrn" not in layout.feature_tags(gsub):
        return
    mapping = layout.single_mapping(gsub, layout.feature_lookups(gsub, "rvrn"))
    for st in font["cmap"].tables:
        if st.format != 14:
            st.cmap = {cp: mapping.get(g, g) for cp, g in st.cmap.items()}
    layout.drop_features(gsub, {"rvrn"})


def standalone(font: TTFont) -> TTFont:
    """The font cut down to the glyphs its own characters reach."""
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.layout_scripts = ["*"]
    opts.name_IDs = ["*"]
    opts.name_languages = ["*"]
    opts.name_legacy = True
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.hinting = True
    opts.prune_unicode_ranges = False
    opts.prune_codepage_ranges = False
    opts.drop_tables = []
    data = io.BytesIO()
    font.save(data)
    out = TTFont(io.BytesIO(data.getvalue()))
    s = subset.Subsetter(opts)
    s.populate(unicodes=out.getBestCmap().keys())
    s.subset(out)
    return out


def cut_font(src: Path, out: Path, static: bool) -> None:
    font = TTFont(src)
    if static:
        bake_rvrn(font)
    single = standalone(font)
    single.recalcBBoxes = not static
    stamps.save(single, out)


def key(src: Path, static: bool) -> str:
    return stamps.digest(
        stamps.file(src), static, stamps.sources(bake_rvrn, standalone, cut_font, stamps.save),
        stamps.modules("mapotofu.layout"), stamps.versions("fonttools"),
    )
