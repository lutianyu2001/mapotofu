# mapotofu
<p align="right">
    <strong>English</strong> | <a href="./README/README_CN.md">中文</a> | <a href="./README/README_JP.md">日本語</a>
</p>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

mapotofu is a build program for CJK composite fonts: it merges a CJK font with a Latin font and regular-script italics into hinted variable and static fonts, from one TOML file per font project.

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

The CJK part comes from the variable region fonts of Source Han Sans; the Latin part and the regular-script ideographs of the italics come from the fonts the project names.

## Features

- **Variable and static**: CFF2 variable-weight fonts, and static CFF instances of the named weights.
- **Families**: any of Gothic, UI and Mono.
  - Gothic: curly quotes, the middle dot, the ellipsis and the em dash are full width, in the forms of the region.
  - UI: curly quotes keep their proportional width, as in Latin text.
  - Mono: fixed pitch, Latin and punctuation in half-width cells (a Latin source's `scale` makes it fit).
- **Regions**: any of SC, TC and J, each with its own glyph forms, language system and local names.
- **Extensions**: ideographs outside each region's common list go into separate extension fonts, so the main fonts stay small.
- **Italics**: Latin italics with regular-script ideographs; the variable italics switch between regular-script weights along the weight axis (`rvrn`), and each static italic takes the nearest one.
- **Hint cache**: hints are kept per glyph in the project's `hints/`, so each glyph is hinted once and later builds take its hints from there.
- **Incremental**: work is redone only where what it is made from changed (sources, configuration, code, library versions); an interrupted or failed run is resumed by running it again.
- **Collections**: fonts of one pool share their glyph tables, which an OTC stores once.

## Prerequisites

- Python ≥3.12
- [uv](https://docs.astral.sh/uv/)
- Dependencies, installed with mapotofu: afdko ≥5.0.1 (otfautohint and tx), fontTools ≥4.68.0, cffsubr ≥0.4.0, brotli ≥1.2.1
- Memory: subroutinizing a static font takes about 100 times its size. mapotofu records what each job took in `build/memory.json` and starts a job only when that much memory is free.

## Installation

### As a Dependency of the Font Project (Recommended)

1. In the font project (a uv project with a `pyproject.toml`), add mapotofu:

   ```bash
   uv add "git+https://github.com/lutianyu2001/mapotofu"
   ```

2. Run it from the project:

   ```bash
   uv run mapo all
   ```

Note: a font project that wants the same fonts from the same tag should pin mapotofu to a commit or a tag, e.g. `uv add "git+https://github.com/lutianyu2001/mapotofu" --rev <commit>`.

### As a Tool

```bash
uvx --from "git+https://github.com/lutianyu2001/mapotofu" mapo all
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

Run in a font project, i.e. the directory holding `mapotofu.toml` or one below it. `MAPOTOFU_ROOT` names the project when run from elsewhere. `mapo` and `mapotofu` are the same command.

```shell
mapo [-h] [-j JOBS] [--only [ONLY ...]]
     {fetch,fonts,desktop,all,prune-hints,collections,release}
```

| Command | Description |
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
    - Fonts such as `Gothic-SC-Upright`, or pools such as `Italic-SC`

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
| `[fonts]` | Regions, families, the weight axis and its masters, the CJK, Latin and regular-script sources | Builds the fonts anew |
| `[meta]` | Version, designer, copyright, license, vendor ID, named weights, family and style names | Only finalizes the built fonts again |
| `[hints]` | Where the hint cache keeps the hints of each source's glyphs | Second step only |
| `[package]` | The name of the collections and their zips | Second step only |

The comments in `tests/project/mapotofu.toml` explain each key.

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
  - Python 3.12.3, afdko 5.0.1, fontTools 4.68.0, cffsubr 0.4.0
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
