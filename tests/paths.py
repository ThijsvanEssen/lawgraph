"""Where the tests find the repository, its source and their fixtures."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "lawgraph"
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"


def fixture_text(name: str, *, sub: str | None = None) -> str:
    """The text of the fixture *name* (in the directory *sub* of the fixtures)."""
    return (FIXTURES / sub / name if sub else FIXTURES / name).read_text(
        encoding="utf-8"
    )
