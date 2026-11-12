# mapotofu
<p align="right">
    <strong>English</strong> | <a href="https://github.com/lutianyu2001/mapotofu/blob/main/README/README_CN.md">中文</a> | <a href="https://github.com/lutianyu2001/mapotofu/blob/main/README/README_JP.md">日本語</a>
</p>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Release](https://img.shields.io/github/v/release/lutianyu2001/mapotofu)](https://github.com/lutianyu2001/mapotofu/releases)
[![PyPI Version](https://img.shields.io/pypi/v/mapotofu)](https://pypi.org/project/mapotofu/)<br>
[![CI](https://github.com/lutianyu2001/mapotofu/actions/workflows/ci.yml/badge.svg)](https://github.com/lutianyu2001/mapotofu/actions/workflows/ci.yml)

mapotofu is a build program for CJK composite fonts: it merges a CJK font with a Latin font, and optionally CJK italic sources (a regular-script or slanted font drawn as such), into hinted variable and static fonts, from one TOML file per font project.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Font Project Layout](#font-project-layout)
- [Configuration](#configuration)
- [Output Files](#output-files)
- [Testing](#testing)
- [Compatibility](#compatibility)
- [Disclaimer](#disclaimer)
- [License](#license)
- [Author](#author)

## Overview

A font project is a directory holding a `mapotofu.toml`. mapotofu reads it, downloads the source fonts the project lists, builds every font of every family, region and style in two steps, and packs the result into zip files for a release:

1. **Fonts**: each font is assembled from the sources as an unhinted CFF2 variable font, with the metadata a web package will need.
2. **Desktop**: the variable fonts are hinted with otfautohint, the static weights are instanced from them, and both are packaged as standalone OTF files and OTC collections.

The CJK part comes from the variable region fonts of Source Han Sans; the Latin part and, when the project gives any, the ideographs and kana of the italics come from the fonts the project names.

## Features

- **Variable and static**: CFF2 variable-weight fonts, and static CFF instances of the named weights.
- **Families**: any of Gothic, UI and Mono.
  - Gothic: curly quotes, the middle dot, the ellipsis and the em dash are full width, in the forms of the region.
  - UI: curly quotes keep their proportional width, as in Latin text.
  - Mono: fixed pitch, Latin and punctuation in half-width cells (a Latin source's `scale` makes it fit).
- **Regions**: any of SC, TC and J, each with its own glyph forms, language system and local names.
- **Extensions**: ideographs outside each region's common list go into separate extension fonts, so the main fonts stay small.
- **Italics**: Latin italics with the upright CJK glyphs, or, for the regions listed in `[fonts.italic_cjk]`, with those of the CJK italic sources; the variable italics switch between their weights along the weight axis (`rvrn`), and each static italic takes the nearest one. A source whose em box differs (such as a narrow font) can be scaled (`scale_x`, `scale_y`) and centred in the full width (`advance`).
- **Hint cache**: hints are kept per glyph in the project's `hints/`, so each glyph is hinted once and later builds take its hints from there.
- **Incremental**: work is redone only where what it is made from changed (sources, configuration, code, library versions); an interrupted or failed run is resumed by running it again.
- **Collections**: fonts of one pool share their glyph tables, which an OTC stores once.
- **Tools**: `mapo tool` measures, compares, draws and converts fonts (stroke widths and glyph size, how a family changes with weight, the glyphs that change between two weights unlike their kind, whether two fonts have exactly the same glyphs, the same characters in several fonts side by side, every glyph of a font at several weights, the points of an outline, sample lines, TrueType outlines to OTF); the modules behind them can be imported as a Python library.

## Prerequisites

- Python ≥3.12
- [uv](https://docs.astral.sh/uv/)
- Dependencies, installed with mapotofu: afdko ≥5.0.1 (otfautohint and tx), fontTools ≥4.68.0, cffsubr ≥0.4.0, uharfbuzz ≥0.57.0, brotli ≥1.2.1; for the tools, freetype-py ≥2.5.1, NumPy ≥2.5.4, Pillow ≥13.0.0, scikit-image ≥0.26.0, SciPy ≥1.18.1
- Memory: subroutinizing a static font takes about 100 times its size. mapotofu records what each job took in `build/memory.json` and starts a job only when that much memory is free.

## Installation

### As a Dependency of the Font Project (Recommended)

1. In the font project (a uv project with a `pyproject.toml`), add mapotofu:

   ```bash
   uv add mapotofu
   ```

2. Run it from the project:

   ```bash
   uv run mapo all
   ```

Note: a font project that wants the same fonts from the same tag should pin mapotofu to a version, e.g. `uv add "mapotofu==<version>"`.

### As a Tool

```bash
uvx --from mapotofu mapo all
```

### Building from Source

```bash
git clone https://github.com/lutianyu2001/mapotofu.git
cd mapotofu
uv sync
```

A font project can then take it by path in its `pyproject.toml`:

```toml
[tool.uv.sources]
mapotofu = { path = "../mapotofu", editable = true }
```

## Usage

Run in a font project, i.e. the directory holding `mapotofu.toml` or one below it. `MAPOTOFU_ROOT` names the project when run from elsewhere. `-h`, `--version` and `--man` work in any directory. `mapo` and `mapotofu` are the same command.

```shell
mapo [-h] [-j N] [--only [KEY ...]] [--man] [--version] STEP
```

| Step | Description |
|---------|-------------|
| `fetch` | Download the sources listed in `sources.toml` into `sources/` |
| `fonts` | First step: the unhinted variable fonts in `build/fonts/` |
| `desktop` | Second step: the hinted fonts in `dist/` (OTF, OTC) |
| `all` | Both steps |
| `prune-hints` | Drop entries of the hint cache that no font uses any more (after a source changed) |
| `collections` | Only the OTC collections, from the pooled fonts in `build/pooled/` |
| `release` | Pack `dist/` into `dist/release/*.zip` by family and region |

- `-j, --jobs` (default: 4)
    - Parallel processes; for `desktop`, the pools hinted at once, each over cores/N runs
- `--only`
    - For `fonts`, `desktop` and `all`: only the pools of these fonts, such as `Gothic-SC-Upright`, or these pools, such as `Italic-SC`
- `--man`
    - Show the manual (see [Manual](#manual))
- `--version`
    - Print the version

Recommended order for a new project:

1. Download the sources:

   ```bash
   uv run mapo fetch
   ```

2. Build everything:

   ```bash
   uv run mapo all
   ```

3. Pack the release:

   ```bash
   uv run mapo release
   ```

*If a run stops (out of memory, interrupted), run the same command again: finished work is kept.*

### Tools

`mapo tool NAME` runs one of the tools that come with mapotofu. They take font files and need no font project, so they run in any directory; `mapo tool` lists them and `mapo tool NAME -h` shows the arguments of one.

| Tool | Description |
|---------|-------------|
| `ttf2otf FONT OUT.otf` | A font with TrueType outlines made into an OTF with PostScript outlines (CFF), subroutinized; the other direction is AFDKO's `otf2ttf` |
| `points FONT TEXT` | The points of glyphs' outlines as the font stores them: number, x, y, on the curve or off; `--box X0 Y0 X1 Y1` for one part of a glyph |
| `same FONT FONT` | Whether two fonts have exactly the same glyphs (outlines and advance widths), and which differ: the check that a change left the fonts alone. Exit status 0 if the same, 1 if not |
| `sheet OUT.png TEXT FONT...` | The same characters in several fonts, a row each, to compare by eye; with `--zoom CHAR X Y WIDTH`, one spot of a glyph in each font instead |
| `specimen FONT OUT.png` | Sample lines of a font at several weights, shaped as text is |
| `stems FONT...` | Stroke widths (vertical, horizontal, their ratio) and glyph size of fonts, in units of 1000 per em: which weight of a source matches a master, and what `scale` fits one font to another |
| `weights FONT FONT...` | How the measures of a family change with weight: the strokes, the width of the ink, the side bearings and the advance of each weight in percent of one of them |
| `change LIGHT HEAVY` | The glyphs that change between two weights of a font unlike the others of their kind (ink, thick and thin strokes, width, height, advance), the furthest off first: where to look in a weight that was derived from another. `--reference LIGHT HEAVY` takes the spread a kind may have from another family |
| `proof OUT FONT...` | Every glyph of a font, a cell a font, into `OUT-01.png`, `OUT-02.png`, ...: the weights of a variable font, to see that every glyph interpolates, or two builds |

A `FONT` is a file, a face of a collection (`Font.ttc#2`) or a place on the axes of a variable font (`Font[wght].ttf@wght=500`).

Example:

```bash
mapo tool stems <FONT_A> "<FONT_B>@wght=400"
mapo tool sheet <OUT.png> "永国あA" <FONT_A> "<FONT_B>@wght=400"
```

The tools are modules of the package `mapotofu.tools`, and their functions can be imported, as can the two modules they are made of: `mapotofu.tools.raster` (fonts opened by such a spec, their glyphs rasterised) and `mapotofu.tools.skeleton` (the skeleton of a glyph as a graph, with the width of its strokes and strokes traced through junctions).

```python
from mapotofu.tools.raster import FontSource
from mapotofu.tools.stems import font_stems

print(font_stems(FontSource("<FONT>")))
```

### Manual

`man mapo` (or `man mapotofu`) is the whole manual, in English and in Chinese: the steps and options, and every key of `mapotofu.toml` and `sources.toml`, with a complete example. mapotofu installs it into its environment, so `man` finds it wherever that environment's `bin` is on `PATH`, as under `uv run`:

```bash
uv run man mapo
```

`mapo --man` shows the same page from anywhere: in the pager, in the language of the locale.

## Font Project Layout

| Path | Contents |
|------|----------|
| `mapotofu.toml` | The fonts' configuration (see [Configuration](#configuration)) |
| `sources.toml` | Where the source fonts are downloaded from, with their SHA-256 |
| `data/common-<region>.txt` | The common ideographs of each region, one hexadecimal code point per line (`#` starts a comment); the others go into the extension fonts |
| `hints/` | The hint cache, and the list of glyphs left unhinted; source data, to be committed |
| `OFL.txt` | The fonts' license; `release` packs nothing without it |
| `sources/`, `build/`, `dist/` | Downloaded sources, intermediate files and output; not committed |

`sources.toml` lists zip archives, with the members to take, and single files:

```toml
[[archive]]
url = "<URL of a zip file>"
sha256 = "<SHA-256 of the file>"
members = { "<path inside the zip>" = "<name under sources/>" }

[[file]]
url = "<URL of a font file>"
sha256 = "<SHA-256 of the file>"
```

## Configuration

`mapotofu.toml` has four tables. Which one a change is in decides how much is built again:

| Table | Holds | Changing it |
|-------|-------|-------------|
| `[fonts]` | Regions, families, the weight axis and its masters, the CJK, Latin and (optional) CJK italic sources | Builds the fonts anew |
| `[meta]` | Version, designer, copyright, license, vendor ID, named weights, family and style names | Only finalizes the built fonts again |
| `[hints]` | Where the hint cache keeps the hints of each source's glyphs | Second step only |
| `[package]` | The name of the collections and their zips | Second step only |

The manual explains every key and has a complete example (see [Manual](#manual)); `tests/project/mapotofu.toml` is a full configuration with comments.

## Output Files

| Path | Contents |
|------|----------|
| `build/fonts/*.otf`, `*.json` | First step: unhinted variable fonts sharing a glyph pool, and their metadata |
| `dist/variable/*.otf` | Hinted CFF2 variable fonts, upright and italic |
| `dist/static/*.otf` | Static CFF fonts of the named weights |
| `dist/otc/*.otc` | Collections, variable and static |
| `dist/release/*.zip` | The release: a `-VF.zip` and a `-static.zip` for each family and region, and the collections; each carries `OFL.txt` |

Note: fonts made from other fonts are Modified Versions of them. With sources under the SIL Open Font License, the result must be released under it too, and its names must not use the sources' Reserved Font Names (Source Han Sans reserves "Source").

## Testing

```bash
uv run pytest
```

The tests run on `tests/project`, which builds nothing. Tests on built fonts belong to the font project.

## Compatibility

Tested on:

- Ubuntu 24.04.4 LTS, 32 cores, 32 GB of memory
  - Python 3.12.3, afdko 5.0.1, fontTools 4.68.0, cffsubr 0.4.0, uharfbuzz 0.57.0
  - Source Han Sans 2.005R
- GitHub Actions `ubuntu-latest`, one pool per job

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Adobe Inc. Adobe and Source are either registered trademarks or trademarks of Adobe in the United States and/or other countries and are referenced here solely for descriptive purposes.

## License

Copyright 2026 Tianyu (Sky) Lu

The entire repository is licensed under the Apache License, Version 2.0 
(the "License"); you may not use any file in this repository except in 
compliance with the License. You may obtain a copy of the License at

```plaintext
http://www.apache.org/licenses/LICENSE-2.0
```

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

## Author

Tianyu (Sky) Lu
