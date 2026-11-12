"""Tools around the fonts mapotofu builds and the fonts it builds them from, and the library
they are made of.

    mapo tool                 list the tools
    mapo tool NAME ...        run one (mapo tool NAME -h: its options)

Each tool is a module here with `parser()` and `main(argv)`, and its functions can be imported
(`from mapotofu.tools.stems import font_stems`). None of them reads a font project: they take
font files and run anywhere.

    raster      fonts by a spec (file, face of a collection, place on the axes), glyphs rasterised
    skeleton    the skeleton of a glyph as a graph: stroke widths, strokes traced through junctions
    stems       tool and functions: stroke widths and glyph size of fonts
    ttf2otf     tool and function: a font with TrueType outlines made into an OTF (CFF outlines)
    change      tool and functions: how each glyph changes between two weights, and those unlike their kind
    points      tool and functions: the points of glyphs' outlines
    proof       tool and functions: every glyph of a font, a cell a weight or a build
    same        tool and function: whether two fonts have exactly the same glyphs
    sheet       tool and functions: the same characters in several fonts, to compare by eye
    specimen    tool and function: sample lines of a font at several weights
    weights     tool and functions: how the measures of a family change with weight
"""

from __future__ import annotations

import sys
from importlib import import_module

# The tools and what the help says of each.
TOOLS = {
    "change": "the glyphs that change between two weights unlike the others of their kind",
    "points": "the points of glyphs' outlines, numbered, on-curve or off",
    "proof": "every glyph of a font, a cell a weight or a build, as PNGs",
    "same": "whether two fonts have exactly the same glyphs",
    "sheet": "the same characters in several fonts, a row each, as a PNG",
    "specimen": "sample lines of a font at several weights, as a PNG",
    "stems": "stroke widths and glyph size of fonts",
    "ttf2otf": "a font with TrueType outlines made into an OTF (CFF outlines)",
    "weights": "how the measures of a family change with weight",
}


def parser(name: str):
    """The argument parser of a tool."""
    return import_module(f"{__name__}.{name}").parser()


def usage(prog: str) -> str:
    width = max(map(len, TOOLS))
    return (f"usage: {prog} tool NAME [ARGUMENT ...]\n\ntools:\n"
            + "\n".join(f"  {name:<{width}}  {text}" for name, text in TOOLS.items())
            + f"\n\n{prog} tool NAME -h shows the arguments of a tool.\n")


def main(argv: list[str], prog: str = "mapo") -> None:
    """Run the tool argv[0] with the arguments after it; with none, or -h, list the tools."""
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(usage(prog))
        return
    if argv[0] not in TOOLS:
        sys.stderr.write(usage(prog))
        raise SystemExit(f"{prog} tool: no tool {argv[0]}")
    import_module(f"{__name__}.{argv[0]}").main(argv[1:])
