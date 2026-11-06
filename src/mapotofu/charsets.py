"""Which source each code point is taken from (SPEC 2), and the three tiers of ideographs (PLAN 3)."""

from __future__ import annotations

import enum
import functools

import unicodedata2

from .config import DATA


class Cat(enum.Enum):
    IDEO = "ideographs"  # SPEC 2.1
    HANGUL = "hangul"  # SPEC 2.2, not included
    WESTERN = "western"  # SPEC 2.3
    WS = "width-sensitive"  # SPEC 2.4
    AS = "regional punctuation"  # SPEC 2.5
    FEMISC = "far-east misc"  # SPEC 2.6
    LONGDASH = "long dashes"  # SPEC 2.7


IDEO_RANGES = (
    (0x2E80, 0x2FFF),
    (0x3192, 0x319F),
    (0x31C0, 0x31EF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFA6F),
    (0x20000, 0x3FFFF),
)
HANGUL_RANGES = (
    (0x1100, 0x11FF),
    (0xA960, 0xA97F),
    (0xD7B0, 0xD7FF),
    (0x3130, 0x318F),
    (0x3200, 0x321E),
    (0x3260, 0x327F),
    (0xAC00, 0xD7AF),
    (0xFFA1, 0xFFDC),
)
# Full-width forms that differ between regions belong to AS rather than WS (SPEC 2.4).
REGIONAL_FULLWIDTH = frozenset(
    (0xFF01, 0xFF08, 0xFF09, 0xFF0C, 0xFF0E, 0xFF1A, 0xFF1B, 0xFF1F, 0xFF3B, 0xFF3D, 0xFF5B, 0xFF5D)
)
FEMISC_RANGES = (
    (0x3003, 0x3007),
    (0x3012, 0x3013),
    (0x3020, 0x33FF),
    (0x1AFF0, 0x1B12F),
    (0x1F000, 0x1F2FF),
)
# Taken from the CJK source even where the Latin source of Gothic and UI has them (SPEC 2.9).
CJK_ONLY_IN_PROPORTIONAL = ((0x20DD, 0x20DE), (0x2460, 0x24FF), (0x2776, 0x2788), (0xE000, 0xF8FF))
# Mono takes these from the Latin source wherever it has them (SPEC 3.1).
LATIN_FIRST_IN_MONO = ((0x00B7, 0x00B7), (0x2000, 0x209F))


def _in(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def category(cp: int) -> Cat:
    if _in(cp, IDEO_RANGES):
        return Cat.IDEO
    if _in(cp, HANGUL_RANGES):
        return Cat.HANGUL
    if cp in (0x2E3A, 0x2E3B):
        return Cat.LONGDASH
    if (cp <= 0x1FFF and cp != 0x00B7) or 0x2070 <= cp <= 0x218F:
        return Cat.WESTERN
    if 0x2000 <= cp <= 0x200F or 0x20A0 <= cp <= 0x2FFF:
        return Cat.WS
    if 0xFF01 <= cp <= 0xFF5E and cp not in REGIONAL_FULLWIDTH:
        return Cat.WS
    if _in(cp, FEMISC_RANGES):
        return Cat.FEMISC
    return Cat.AS


def source_of(cp: int, family: str, in_cjk: bool, in_latin: bool) -> str | None:
    """Return "cjk", "latin" or None for a code point of a main font (SPEC 2.8, 2.9, 3.1)."""
    cat = category(cp)
    if cat is Cat.HANGUL:
        return None
    if cat is Cat.IDEO:
        return "cjk" if in_cjk else None
    if family != "Mono" and _in(cp, CJK_ONLY_IN_PROPORTIONAL):
        in_latin = False
    if cat is Cat.LONGDASH:
        if family == "Mono":
            return "latin" if in_latin else None
        return "cjk" if in_cjk else ("latin" if in_latin else None)
    if family == "Mono" and _in(cp, LATIN_FIRST_IN_MONO) and in_latin:
        return "latin"
    if cat is Cat.AS:
        order = ("cjk", "latin")
    else:  # WESTERN, WS, FEMISC: the Latin source wins conflicts
        order = ("latin", "cjk")
    for src in order:
        if (src == "cjk" and in_cjk) or (src == "latin" and in_latin):
            return src
    return None


# Kana that the italics take from the regular-script source (PLAN 5). Punctuation-like
# characters inside the kana blocks stay with Source Han Sans like other symbols.
KANA_RANGES = ((0x3041, 0x309F), (0x30A1, 0x30FA), (0x30FC, 0x30FF), (0x31F0, 0x31FF), (0x1AFF0, 0x1B16F))


# Kana that must move or turn in vertical text: small kana and the long vowel mark. The italics
# take these from the regular-script source only where it has vertical forms for them; other
# kana are upright in vertical text anyway (Source Han Sans has vertical designs for all kana,
# a refinement the regular-script sources lack).
KANA_VERTICAL = frozenset(
    [ord(c) for c in "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶー"]
    + list(range(0x31F0, 0x3200))
    + [0x1B132, 0x1B150, 0x1B151, 0x1B152, 0x1B155, 0x1B164, 0x1B165, 0x1B166, 0x1B167]
)


def is_kana(cp: int) -> bool:
    return _in(cp, KANA_RANGES) and cp not in (0x3099, 0x309A)


@functools.cache
def common(region: str) -> frozenset[int]:
    return frozenset(_read(f"common-{region.lower()}.txt"))


def _read(name: str) -> list[int]:
    out = []
    for line in (DATA / name).read_text().splitlines():
        if line and not line.startswith("#"):
            out.append(int(line.split()[0], 16))
    return out


def is_tiered(cp: int) -> bool:
    """Ideographs that are split between the main font and the extensions: unified and
    compatibility ideographs, not radicals, strokes or kanbun marks."""
    if category(cp) is not Cat.IDEO:
        return False
    name = unicodedata2.name(chr(cp), "")
    return name.startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))
