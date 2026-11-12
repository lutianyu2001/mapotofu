"""Standalone fonts cut from pool-backed ones."""

from __future__ import annotations

import io
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

from . import layout, stamps


def bake_rvrn(font: TTFont) -> None:
    """In a static italic, put the CJK italic weight chosen by rvrn into the cmap."""
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
    # The average width and the longest context of OS/2 are the pool's until now.
    opts.recalc_average_width = True
    opts.recalc_max_context = True
    data = io.BytesIO()
    font.recalcTimestamp = False  # keep the date meta.finalize set (see stamps.save)
    # The boxes and extremes are the pool's here; saving the cut font sets its own, from the
    # glyphs left and their side bearings.
    font.recalcBBoxes = False
    font.save(data)
    out = TTFont(io.BytesIO(data.getvalue()))
    s = subset.Subsetter(opts)
    s.populate(unicodes=out.getBestCmap().keys())
    s.subset(out)
    return out


def name_cff(font: TTFont) -> None:
    """Give the CFF of a static font the font's own name and what post says of it. The pool's
    CFF, which the collections share, is named after the pool and says nothing of pitch, slope
    or underline, which differ between its fonts."""
    name, post = font["name"], font["post"]

    def text(*ids: int) -> str | None:
        found = next((r.toUnicode() for i in ids if (r := name.getName(i, 3, 1, 0x409))), None)
        return found if found and found.isascii() else None

    cff = font["CFF "].cff
    top = cff.topDictIndex[0]
    if ps := text(6):
        cff.fontNames = [ps]
    style = text(17, 2) or "Regular"
    values = {
        "FullName": text(4),
        "FamilyName": text(16, 1),
        "Weight": style.removesuffix("Italic").strip() or "Regular",
        "isFixedPitch": int(bool(post.isFixedPitch)),
        "ItalicAngle": post.italicAngle,
        # post gives the top of the underline, CFF its middle.
        "UnderlinePosition": post.underlinePosition - post.underlineThickness / 2,
        "UnderlineThickness": post.underlineThickness,
    }
    for field, value in values.items():
        if value is not None:
            setattr(top, field, value)


def cut_font(src: Path, out: Path, static: bool) -> None:
    font = TTFont(src)
    if static:
        bake_rvrn(font)
    single = standalone(font)
    if static:
        name_cff(single)
    stamps.save(single, out)


def key(src: Path, static: bool) -> str:
    return stamps.digest(
        stamps.file(src), static, stamps.sources(bake_rvrn, standalone, name_cff, cut_font, stamps.save),
        stamps.modules("mapotofu.layout"), stamps.versions("fonttools", "uharfbuzz"),
    )
