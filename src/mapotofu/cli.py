"""Command line entry point: mapo (or mapotofu, python -m mapotofu).

The options are read here, before anything of a font project is: the help, the version and the
manual are shown from any directory. A step then reads the project's mapotofu.toml
(mapotofu.config, through mapotofu.build) and needs to be run in a font project. `mapo tool`
runs one of the tools (mapotofu.tools), which take font files and need no font project.
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import version
from pathlib import Path

from . import tools

# The steps and what the help says of each; mapotofu.build.step runs them.
STEPS = {
    "fetch": "download the sources listed in sources.toml into sources/",
    "fonts": "first step: the unhinted variable fonts in build/fonts/",
    "desktop": "second step: the hinted fonts in dist/ (OTF, OTC)",
    "all": "both steps",
    "prune-hints": "drop the entries of the hint cache that no font uses any more",
    "collections": "only the OTC collections, from the pooled fonts in build/pooled/",
    "release": "pack dist/ into dist/release/*.zip by family and region",
}


class _Manual(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        from . import manual

        manual.show()
        parser.exit()


def parser() -> argparse.ArgumentParser:
    name = Path(sys.argv[0]).name
    width = max(map(len, STEPS))
    ap = argparse.ArgumentParser(
        prog=name if name in ("mapotofu", "mapo") else "python -m mapotofu",
        description="Build the CJK composite fonts of a font project: the directory of a mapotofu.toml, "
        "or one below it (MAPOTOFU_ROOT names the project when run from elsewhere).",
        epilog="steps:\n"
        + "\n".join(f"  {step:<{width}}  {text}" for step, text in STEPS.items())
        + f"\n\ntools, run from anywhere ({name if name in ('mapotofu', 'mapo') else 'mapo'} tool lists them):\n"
        + "\n".join(f"  tool {tool:<{max(map(len, tools.TOOLS))}}  {text}" for tool, text in tools.TOOLS.items())
        + "\n\nThe manual explains every key of mapotofu.toml: man mapo, or mapo --man.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("step", choices=tuple(STEPS), metavar="STEP", help="what to do (see below)")
    ap.add_argument(
        "-j", "--jobs", type=int, default=4, metavar="N",
        help="parallel processes (default: 4); for desktop, the pools hinted at once, each over cores/N runs",
    )
    ap.add_argument(
        "--only", nargs="*", metavar="KEY",
        help="for fonts, desktop and all: only the pools of these fonts (such as Gothic-SC-Upright) "
        "or these pools (such as Italic-SC)",
    )
    ap.add_argument("--man", action=_Manual, nargs=0, help="show the manual and exit")
    ap.add_argument("--version", action="version", version=f"mapotofu {version('mapotofu')}")
    return ap


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["tool"]:
        name = Path(sys.argv[0]).name
        tools.main(argv[1:], name if name in ("mapotofu", "mapo") else "python -m mapotofu")
        return
    args = parser().parse_args(argv)
    if args.step == "fetch":  # reads only the project's sources.toml: before any font is described
        from . import fetch

        fetch.main()
        return
    from . import build  # reads the project's mapotofu.toml

    build.step(args.step, args.jobs, args.only)


if __name__ == "__main__":
    main()
