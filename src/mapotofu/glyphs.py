"""Outlines and metrics of every output glyph at every master, and the width rules of SPEC 3.2."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from fontTools.pens.boundsPen import ControlBoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen

from .config import MASTERS

Outline = list  # RecordingPen.value


@dataclass
class Master:
    outline: Outline
    width: float
    height: float = 1000
    vorg: float = 880


@dataclass
class Glyph:
    """One output glyph: either one Master per entry of config.MASTERS, or a single Master
    used at every weight (static glyphs such as the ideographs of a CJK italic source)."""

    masters: list[Master]
    # True when the outline is linear in the axis' normalized coordinate on each side of the
    # default (glyphs of Source Han Sans, see sources.axis_map): only the extreme and default
    # masters then carry its outline, and the variable font stores two deltas instead of seven.
    linear: bool = False

    def at(self, i: int) -> Master:
        return self.masters[0] if len(self.masters) == 1 else self.masters[i]

    @property
    def static(self) -> bool:
        return len(self.masters) == 1


@dataclass
class GlyphStore:
    glyphs: dict[str, Glyph] = field(default_factory=dict)

    def add(self, name: str, glyph: Glyph) -> None:
        old = self.glyphs.get(name)
        if old is not None and old is not glyph and old.masters is not glyph.masters:
            # The same name must always mean the same glyph.
            assert len(old.masters) == len(glyph.masters), name
        self.glyphs.setdefault(name, glyph)

    def __getitem__(self, name: str) -> Glyph:
        return self.glyphs[name]

    def __contains__(self, name: str) -> bool:
        return name in self.glyphs


def record(glyph, glyphset) -> Outline:
    pen = DecomposingRecordingPen(glyphset)
    glyph.draw(pen)
    return pen.value


def map_points(outline: Outline, fn) -> Outline:
    out = []
    for op, args in outline:
        out.append((op, tuple(fn(x, y) for x, y in args)))
    return out


def bounds(outline: Outline):
    pen = ControlBoundsPen(None)
    for op, args in outline:
        getattr(pen, op)(*args)
    return pen.bounds


def charstring(m: Master, empty: bool = False):
    pen = T2CharStringPen(round(m.width), None)
    for op, args in [] if empty else m.outline:
        getattr(pen, op)(*args)
    # Unoptimized, so that every master keeps the same commands (a zero-length line would be dropped).
    return pen.getCharString(optimize=False)


# --- width rules (SPEC 3.2, 3.3) ---------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A width rule. kind: "center", "stretch", "right" (move the outline right by the change
    of width) or "keep" (change the width only); target is the new advance width.
    "ceil" rounds the width up to a multiple of a half em, at most a full em, then centers."""

    kind: str
    target: int = 0

    @property
    def suffix(self) -> str:
        return {"center": "c", "stretch": "s", "right": "r", "keep": "k", "ceil": "c"}[self.kind]


def resolve(rule: Rule, widths: list[float]) -> Rule | None:
    """Fix the target of a rule from the default master's width; None if it changes nothing."""
    if rule.kind == "ceil":
        w = widths[MASTERS.index(400)] if len(widths) > 1 else widths[0]
        if round(w) == 0:
            return None  # a combining mark: it takes no cell
        target = min(1000, max(500, math.ceil(round(w) / 500) * 500))
        rule = Rule("center", target)
    if all(round(w) == rule.target for w in widths):
        return None
    return rule


def apply(rule: Rule, m: Master) -> Master:
    w, t = m.width, rule.target
    d = t - w
    if rule.kind == "center":
        fn = lambda x, y: (x + d / 2, y)  # noqa: E731
    elif rule.kind == "right":
        fn = lambda x, y: (x + d, y)  # noqa: E731
    elif rule.kind == "keep":
        fn = None
    elif rule.kind == "stretch":
        fn = lambda x, y: (x + d if x >= w / 2 else x, y)  # noqa: E731
    else:
        raise ValueError(rule.kind)
    outline = map_points(m.outline, fn) if fn else m.outline
    return Master(outline, t, m.height, m.vorg)


def transformed(rule: Rule, glyph: Glyph) -> Glyph:
    return Glyph([apply(rule, m) for m in glyph.masters], glyph.linear)


def renamed(name: str, rule: Rule | None) -> str:
    return name if rule is None else f"{name}.{rule.suffix}{rule.target}"
