"""Whether two fonts have the same glyphs, exactly: outline for outline, advance for advance.

    mapo tool same FONT FONT [--list N]

    from mapotofu.tools.same import compare

    found = compare("before.otf", "after.otf")
    found.same, found.different, found.only_first, found.only_second

For checking that a change to the program or to a configuration left the fonts alone, or
touched only the glyphs it was meant to: after a refactoring nothing may differ. A glyph is the
same in both fonts when drawing it gives the same lines and curves at the same coordinates and
its advance width is the same; components are drawn out first, so a glyph made of components
equals the same shape drawn directly. Glyphs are matched by name.

A comparison of rendered images (diffenator3) answers another question, which glyphs changed
visibly: it passes over changes of a unit or two, which this one counts.

The same shape drawn with other curves is another outline: a font with TrueType outlines and
its conversion to CFF differ in every glyph. A variable font is compared at its default
location only.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from .raster import parse_spec


@dataclass
class Found:
    """What compare found: the names of the glyphs in both fonts (`common`), of those among them
    that differ (`different`: `outline` and `advance` say in what, a glyph may be in both), and
    of the glyphs only one font has; `chars` maps the names that have a character to it."""

    common: list[str] = field(default_factory=list)
    different: list[str] = field(default_factory=list)
    outline: set[str] = field(default_factory=set)
    advance: set[str] = field(default_factory=set)
    only_first: list[str] = field(default_factory=list)
    only_second: list[str] = field(default_factory=list)
    chars: dict[str, str] = field(default_factory=dict)

    @property
    def same(self) -> bool:
        return not (self.different or self.only_first or self.only_second)


def _open(spec: str) -> TTFont:
    path, index, _ = parse_spec(spec)
    return TTFont(path, fontNumber=index, lazy=True)


def _drawn(glyphs, name: str):
    pen = DecomposingRecordingPen(glyphs)
    glyphs[name].draw(pen)
    return pen.value


def compare(first: str, second: str) -> Found:
    """Compare the glyphs of two fonts (files, or faces of collections as Font.ttc#2)."""
    a, b = _open(first), _open(second)
    ga, gb = a.getGlyphSet(), b.getGlyphSet()
    in_b = set(b.getGlyphOrder())
    found = Found()
    for font in (b, a):                       # (the first font's characters name a glyph both have)
        found.chars.update({name: chr(code) for code, name in (font.getBestCmap() or {}).items()})
    for name in a.getGlyphOrder():
        if name not in in_b:
            found.only_first.append(name)
            continue
        found.common.append(name)
        if ga[name].width != gb[name].width:
            found.advance.add(name)
        if _drawn(ga, name) != _drawn(gb, name):
            found.outline.add(name)
        if name in found.advance or name in found.outline:
            found.different.append(name)
    in_a = set(a.getGlyphOrder())
    found.only_second = [name for name in b.getGlyphOrder() if name not in in_a]
    return found


def parser(prog: str = "mapo tool same") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Tell whether two fonts have exactly the same glyphs: outlines and advance widths. "
        "The exit status is 0 if they have, 1 if not.",
        epilog="A FONT is a file or a face of a collection (Font.ttc#2).",
    )
    ap.add_argument("first", metavar="FONT")
    ap.add_argument("second", metavar="FONT")
    ap.add_argument("--list", type=int, default=40, metavar="N", dest="shown",
                    help="name at most N of the glyphs that differ, and of those only one font has (default: 40)")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    found = compare(args.first, args.second)

    def named(names: list[str]) -> str:
        shown = [f"{name} {found.chars[name]}" if name in found.chars else name for name in names[:args.shown]]
        return ", ".join(shown) + (f", ... ({len(names) - args.shown} more)" if len(names) > args.shown else "")

    print(f"glyphs: {len(found.common)} in both, {len(found.only_first)} only in the first, "
          f"{len(found.only_second)} only in the second")
    print(f"different: {len(found.different)} (outline {len(found.outline)}, advance {len(found.advance)})")
    for title, names in (("different", found.different), ("only in the first", found.only_first),
                         ("only in the second", found.only_second)):
        if names and args.shown > 0:
            print(f"{title}: {named(names)}")
    print("the same" if found.same else "not the same")
    sys.exit(0 if found.same else 1)


if __name__ == "__main__":
    main()
