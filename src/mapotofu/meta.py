"""name, OS/2, head, hhea, post and STAT of the output fonts (SPEC 6)."""

from __future__ import annotations

import math
import os

from fontTools.otlLib.builder import buildStatTable
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._f_v_a_r import NamedInstance
from fontTools.ttLib.tables.O_S_2f_2 import Panose

from . import sources
from .config import (
    AXIS_DEFAULT,
    CODEPAGE_BIT,
    COPYRIGHT_OWN,
    DESIGNER,
    EXT_CJK_NAMES,
    FAMILY_NAMES,
    KAI,
    LATIN,
    LICENSE,
    LICENSE_URL,
    REGIONS,
    SHS,
    SOURCES,
    STATIC_WEIGHTS,
    VENDOR,
    VERSION,
    WEIGHT_CLASS,
    WIN_LANG,
)

# Vertical metrics: Gothic and UI keep those of Source Han Sans; Mono, made for terminals, puts
# the ideographic em box in a 1.2 em line.
LINE = {"Mono": (980, -220)}
LINE_DEFAULT = (1160, -288)


def families(view) -> tuple[str, dict[str, str]]:
    """English family name and local names by region."""
    if view.region == "CJK":
        return EXT_CJK_NAMES
    en, local = FAMILY_NAMES[view.family][view.region]
    return en, {view.region: local}


def style_name(weight: str, italic: bool) -> str:
    if italic:
        return "Italic" if weight == "Regular" else f"{weight} Italic"
    return weight


def _legacy(weight: str, italic: bool) -> tuple[str, str]:
    """(suffix of nameID 1, nameID 2) for the four-style model (SPEC 6.1)."""
    if weight in ("Regular", "Bold"):
        return "", style_name(weight, italic)
    short = weight.replace("Extra", "X")
    return f" {short}", "Italic" if italic else "Regular"


def _source_paths(view) -> list[str]:
    paths = [SHS[view.shs_region]]
    if not view.is_ext:
        paths.append(LATIN[(view.family, view.italic)].path)
    if view.italic:
        for w in KAI[view.region]:
            paths.extend(s.path for s in w.sources)
    return list(dict.fromkeys(paths))


def copyright(view) -> str:
    lines = [COPYRIGHT_OWN]
    for p in _source_paths(view):
        text = TTFont(SOURCES / p, lazy=True)["name"].getDebugName(0)
        for line in text.splitlines():
            if line not in lines:
                lines.append(line)
    return "\n".join(lines)


def set_names(font: TTFont, view, weight: str | None) -> None:
    """weight None names a variable font after its default instance."""
    name = font["name"]
    name.names = []
    en, local = families(view)
    w = weight or "Regular"
    style = style_name(w, view.italic)
    suffix, legacy_style = _legacy(w, view.italic)
    ps_family = en.replace(" ", "-")
    ps = f"{ps_family}-{style.replace(' ', '')}"

    def put(nid: int, text: str, lang: int = 0x409) -> None:
        name.setName(text, nid, 3, 1, lang)

    put(0, copyright(view))
    put(5, f"Version {VERSION}")
    put(6, ps)
    put(8, DESIGNER)
    put(9, DESIGNER)
    put(13, LICENSE)
    put(14, LICENSE_URL)
    for lang, fam in [(0x409, en)] + [(WIN_LANG[r], local[r]) for r in REGIONS if r in local]:
        put(1, fam + suffix, lang)
        put(2, legacy_style, lang)
        put(3, f"{en} {style}" if lang == 0x409 else f"{fam} {style}", lang)
        put(4, fam + suffix + ("" if legacy_style == "Regular" else f" {legacy_style}"), lang)
        put(16, fam, lang)
        put(17, style, lang)
    if weight is None:
        put(25, ps_family)
    name.names.sort(key=lambda r: (r.platformID, r.platEncID, r.langID, r.nameID))


def _os2(font: TTFont, view, weight: str | None) -> None:
    os2 = font["OS/2"]
    w = weight or "Regular"
    os2.version = 4
    os2.usWeightClass = WEIGHT_CLASS[w] if weight else AXIS_DEFAULT
    os2.usWidthClass = 5
    os2.fsType = 0
    os2.achVendID = VENDOR
    sel = 1 << 7  # USE_TYPO_METRICS; WWS stays off
    if view.italic:
        sel |= 1 << 0
    if w == "Bold":
        sel |= 1 << 5
    if w == "Regular" and not view.italic:
        sel |= 1 << 6
    os2.fsSelection = sel
    asc, desc = LINE.get(view.family, LINE_DEFAULT)
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = asc, desc, 0
    head = font["head"]
    os2.usWinAscent = max(asc, head.yMax)
    os2.usWinDescent = max(-desc, -head.yMin)
    if not view.is_ext:
        lat = sources.latin(LATIN[(view.family, view.italic)]).font["OS/2"]
        os2.sxHeight, os2.sCapHeight = lat.sxHeight, lat.sCapHeight
    else:
        os2.sxHeight, os2.sCapHeight = 543, 733
    p = Panose()
    for attr in ("bFamilyType", "bSerifStyle", "bWeight", "bProportion", "bContrast", "bStrokeVariation",
                 "bArmStyle", "bLetterForm", "bMidline", "bXHeight"):
        setattr(p, attr, 0)
    p.bFamilyType = 2
    p.bWeight = 1 + os2.usWeightClass // 100
    p.bProportion = 9 if view.family == "Mono" else 0
    os2.panose = p
    os2.recalcUnicodeRanges(font)
    region = "J" if view.region == "CJK" else view.region
    bits = [0, CODEPAGE_BIT[region], 63]  # CP1252, the region's code page, CP437 (Range2 bit 31)
    if view.region == "CJK":
        bits += [CODEPAGE_BIT[r] for r in REGIONS]
    os2.setCodePageRanges(set(bits))
    os2.usDefaultChar = 0
    os2.usBreakChar = 32
    os2.usMaxContext = max(os2.usMaxContext, 1)


def _italic_angle(view) -> float:
    if not view.italic or view.is_ext:
        return 0.0
    return TTFont(SOURCES / LATIN[(view.family, True)].path, lazy=True)["post"].italicAngle


def finalize(font: TTFont, view, weight: str | None = None) -> None:
    """Metadata of a variable font (weight None) or of a static instance."""
    set_names(font, view, weight)
    head = font["head"]
    head.fontRevision = float(VERSION.rsplit(".", 1)[0]) if VERSION.count(".") > 1 else float(VERSION)
    head.flags = 0b1111  # baseline at 0, lsb at 0, integer ppem, instructions depend on size
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "1767225600"))  # 2026-01-01
    head.created = head.modified = epoch + 2082844800
    head.macStyle = (1 if (weight == "Bold") else 0) | (2 if view.italic else 0)
    asc, desc = LINE.get(view.family, LINE_DEFAULT)
    hhea = font["hhea"]
    hhea.ascent, hhea.descent, hhea.lineGap = asc, desc, 0
    angle = _italic_angle(view)
    if angle:
        hhea.caretSlopeRise = 1000
        hhea.caretSlopeRun = round(1000 * math.tan(math.radians(-angle)))
    else:
        hhea.caretSlopeRise, hhea.caretSlopeRun = 1, 0
    post = font["post"]
    post.formatType = 3.0
    post.italicAngle = angle
    if not view.is_ext:
        lat = TTFont(SOURCES / LATIN[(view.family, view.italic)].path, lazy=True)["post"]
        scale = LATIN[(view.family, view.italic)].scale
        post.underlinePosition = round(lat.underlinePosition * scale)
        post.underlineThickness = round(lat.underlineThickness * scale)
    else:
        post.underlinePosition, post.underlineThickness = -125, 50
    post.isFixedPitch = 1 if view.family == "Mono" else 0
    post.mapping, post.extraNames = {}, []
    _os2(font, view, weight)
    if weight is None:
        _instances(font, view)
    _stat(font, view, weight)


def _instances(font: TTFont, view) -> None:
    fvar = font["fvar"]
    name = font["name"]
    en, _ = families(view)
    fvar.axes[0].axisNameID = name.addMultilingualName({"en": "Weight"}, mac=False)
    fvar.instances = []
    for wname, value in STATIC_WEIGHTS.items():
        inst = NamedInstance()
        style = style_name(wname, view.italic)
        inst.subfamilyNameID = name.addMultilingualName({"en": style}, mac=False)
        inst.postscriptNameID = name.addMultilingualName(
            {"en": f"{en.replace(' ', '-')}-{style.replace(' ', '')}"}, mac=False
        )
        inst.coordinates = {"wght": value}
        fvar.instances.append(inst)


def _stat(font: TTFont, view, weight: str | None) -> None:
    values = []
    for wname, value in STATIC_WEIGHTS.items():
        v = {"value": value, "name": wname}
        if wname == "Regular":
            v["flags"] = 0x2
            v["linkedValue"] = 700
        values.append(v)
    ital = (
        {"value": 1, "name": "Italic"}
        if view.italic
        else {"value": 0, "name": "Roman", "flags": 0x2, "linkedValue": 1}
    )
    axes = [
        {"tag": "wght", "name": "Weight", "values": values},
        {"tag": "ital", "name": "Italic", "values": [ital]},
    ]
    if "STAT" in font:
        del font["STAT"]
    buildStatTable(font, axes, elidedFallbackName="Regular")
