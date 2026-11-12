"""The command line (mapotofu.cli) and the manual (mapotofu.manual)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

from mapotofu import cli, manual, tools

SRC = Path(cli.__file__).parent
PAGES = {lang: manual.page(lang).read_text(encoding="utf-8") for lang in ("", "zh_CN")}


def _run(tmp_path, *args: str, **env: str) -> subprocess.CompletedProcess:
    """mapo run in a directory that is no font project, its output not a terminal."""
    clean = {k: v for k, v in os.environ.items() if k not in ("MAPOTOFU_ROOT", "LANGUAGE", "LC_ALL", "LC_MESSAGES")}
    return subprocess.run(
        [sys.executable, "-m", "mapotofu", *args], cwd=tmp_path, env={**clean, "LANG": "C", **env},
        capture_output=True, text=True,
    )


def test_help_and_version_need_no_font_project(tmp_path):
    done = _run(tmp_path, "-h")
    assert done.returncode == 0 and "--only" in done.stdout
    for step in cli.STEPS:
        assert re.search(rf"^  {step} ", done.stdout, re.M), step
    done = _run(tmp_path, "--version")
    assert done.returncode == 0 and done.stdout.strip() == f"mapotofu {version('mapotofu')}"


def test_the_tools_need_no_font_project(tmp_path):
    done = _run(tmp_path, "tool")
    assert done.returncode == 0
    for name in tools.TOOLS:
        assert re.search(rf"^  {name} ", done.stdout, re.M), name
        assert re.search(rf"^  tool {name} ", _run(tmp_path, "-h").stdout, re.M), name
        usage = _run(tmp_path, "tool", name, "-h")
        assert usage.returncode == 0 and usage.stdout.startswith(f"usage: mapo tool {name} "), usage.stdout
    done = _run(tmp_path, "tool", "nothing")
    assert done.returncode == 1 and "no tool nothing" in done.stderr


def test_fetch_reads_only_the_sources_file(tmp_path):
    """A project whose mapotofu.toml describes no font yet fetches its sources: a file by the
    name its entry gives, and nothing again once it is there."""
    upstream = tmp_path / "upstream" / "v1"
    upstream.mkdir(parents=True)
    (upstream / "data.txt").write_text("strokes")
    project = tmp_path / "project"
    project.mkdir()
    (project / "mapotofu.toml").write_text("")
    entry = f'[[file]]\nurl = "{(upstream / "data.txt").as_uri()}"\nsha256 = "{hashlib.sha256(b"strokes").hexdigest()}"\n'
    (project / "sources.toml").write_text(entry + 'name = "strokes-v1.txt"\n\n' + entry)
    done = _run(project, "fetch")
    assert done.returncode == 0, done.stderr
    assert sorted(p.name for p in (project / "sources").iterdir()) == ["_cache", "data.txt", "strokes-v1.txt"]
    (upstream / "data.txt").unlink()
    done = _run(project, "fetch")                     # nothing to download: the files are there
    assert done.returncode == 0 and "downloading" not in done.stderr
    done = _run(project, "fonts")
    assert done.returncode == 1 and "no [fonts] table" in done.stderr


def test_a_step_needs_a_font_project(tmp_path):
    done = _run(tmp_path, "fonts")
    assert done.returncode == 1 and "no mapotofu.toml" in done.stderr


def test_man_writes_the_page_of_the_locale(tmp_path):
    assert _run(tmp_path, "--man").stdout == PAGES[""]
    assert _run(tmp_path, "--man", LANG="zh_CN.UTF-8").stdout == PAGES["zh_CN"]
    assert _run(tmp_path, "--man", LANG="zh_CN.UTF-8", LC_ALL="en_US.UTF-8").stdout == PAGES[""]


def _bold(page: str) -> set[str]:
    """The words a page sets in bold, where it names options, keys and tables."""
    text = "\n".join(line for line in page.splitlines() if line.startswith((".B ", ".BR ")))
    text += "\n" + "\n".join(re.findall(r"\\fB(.*?)\\f[RIP]", page))
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_-]*", text.replace("\\-", "-")))


def _keys(module: str) -> set[str]:
    """The keys a module reads from a TOML file: what it subscripts or gets by a literal name."""
    source = (SRC / module).read_text()
    found = re.findall(r"""\[\s*"([a-z_0-9]+)"\s*\]|\.get\(\s*"([a-z_0-9]+)\"""", source)
    return {subscript or got for subscript, got in found}


@pytest.mark.parametrize("lang", PAGES)
def test_the_manuals_cover_the_options_steps_and_keys(lang):
    page = PAGES[lang]
    assert re.search(rf'^\.TH MAPOTOFU 1 .*"mapotofu {re.escape(version("mapotofu"))}"', page, re.M)
    bold = _bold(page)
    for action in cli.parser()._actions:
        for option in action.option_strings:
            assert option.lstrip("-") in bold, option
    for step in cli.STEPS:
        assert step in bold, step
    for name in tools.TOOLS:
        assert re.search(rf'^\.BR "tool {name}" ', page, re.M), name
        for action in tools.parser(name)._actions:
            for option in action.option_strings:
                assert option.lstrip("-") in bold, (name, option)
    keys = _keys("config.py") | {"min", "default", "max"} | _keys("fetch.py")
    assert {"regions", "scale_x", "from", "code_page_bit", "collection", "members"} <= keys
    for key in sorted(keys):
        assert key in bold, key
    for variable in ("MAPOTOFU_ROOT", "SOURCE_DATE_EPOCH"):
        assert variable in bold, variable


@pytest.mark.parametrize("lang", PAGES)
def test_the_example_of_the_manuals_is_a_configuration(lang, tmp_path):
    blocks = re.findall(r"^\.EX\n(.*?)^\.EE$", PAGES[lang], re.M | re.S)
    (example,) = [b for b in blocks if b.startswith("[fonts]")]
    (tmp_path / "mapotofu.toml").write_text(example.replace("\\-", "-"), encoding="utf-8")
    code = "from mapotofu import config; print(config.COLLECTION, len(config.ITALIC_CJK), config.MASTERS[0])"
    done = subprocess.run(
        [sys.executable, "-c", code], env={**os.environ, "MAPOTOFU_ROOT": str(tmp_path)}, capture_output=True, text=True
    )
    assert done.stdout.split() == ["Example", "1", "250"], done.stderr
    (sources,) = [b for b in blocks if b.startswith("[[archive]]")]
    spec = tomllib.loads(sources.replace("\\-", "-"))
    assert set(spec) == {"archive", "file"} and set(spec["archive"][0]) == {"url", "sha256", "members"}


def test_the_translation_has_the_sections_of_the_original():
    def shape(page: str) -> list[str]:
        return [line.split()[0] for line in page.splitlines() if line.startswith((".SH", ".SS", ".TP", ".EX"))]

    assert shape(PAGES[""]) == shape(PAGES["zh_CN"])
    for name in ("man1/mapo.1", "zh_CN/man1/mapo.1"):
        assert (SRC / "man" / name).read_text() == ".so man1/mapotofu.1\n"
