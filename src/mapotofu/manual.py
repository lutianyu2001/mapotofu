"""The manual, man mapotofu, in English and in Chinese: the pages under man/, which a wheel also
installs where man finds them (share/man of the environment)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.resources import as_file, files

PAGE = "mapotofu.1"  # mapo.1 beside it only names this one


def language() -> str:
    """The directory of the translation the locale asks for, "" for the English original; read
    as gettext reads it, since man chooses its pages the same way."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        if value := os.environ.get(var):
            return "zh_CN" if value.lower().startswith("zh") else ""
    return ""


def page(lang: str | None = None):
    lang = language() if lang is None else lang
    return files("mapotofu").joinpath("man", *([lang] if lang else []), "man1", PAGE)


def show() -> None:
    """Show the manual in the language of the locale. On a terminal man reads it: it formats
    the page and hands it to the pager (MANPAGER, PAGER, else less). Elsewhere the page's source
    is written as it is, for man to read (mapo --man > mapotofu.1, mapo --man | man -l -)."""
    source = page()
    if sys.stdout.isatty():
        if man := shutil.which("man"):
            with as_file(source) as path:
                # man takes a name with a slash in it as a file.
                if subprocess.run([man, str(path)]).returncode == 0:
                    return
        import pydoc

        pydoc.pager(source.read_text(encoding="utf-8"))
        return
    try:
        sys.stdout.write(source.read_text(encoding="utf-8"))
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader left early (mapo --man | head): nothing is wrong, and Python is not to
        # complain when it closes the stream.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
