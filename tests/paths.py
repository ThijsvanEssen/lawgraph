"""Where the tests find the repository, its source and their fixtures."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lawgraph"
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"


def fixture_text(name: str, *, sub: str | None = None) -> str:
    """The text of the fixture *name* (in the directory *sub* of the fixtures)."""
    return (FIXTURES / sub / name if sub else FIXTURES / name).read_text(
        encoding="utf-8"
    )


def python_of_the_suite() -> str:
    """A script standing in for the ``.venv/bin/python`` of the app: the interpreter of the
    suite with the ``lawgraph`` of this checkout, wherever that interpreter's own install
    points (a worktree without a ``.venv`` of its own runs on that of another checkout)."""
    return (
        f'#!/bin/sh\nPYTHONPATH="{ROOT / "src"}${{PYTHONPATH:+:$PYTHONPATH}}" '
        f'exec "{sys.executable}" "$@"\n'
    )
