"""The store is PostgreSQL, and nothing names another database: not the code, its
configuration, its dependencies, its services or its docs."""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

from tests.paths import ROOT, SRC

_OTHER = re.compile(r"arango|\baql\b", re.I)
# The comments of db/ still explain SQL by the semantics it keeps; they go with that SQL.
_EXPLAINED = SRC / "db"
_SCANNED = (
    "pyproject.toml",
    "docker-compose.yml",
    "docker-compose.test.yml",
    ".env.example",
    "README.md",
    "CONTRIBUTING.md",
    ".github",
    "deploy",
    "docs",
    "ops",
    "scripts",
    "src",
    "tests",
)


def _files() -> list[pathlib.Path]:
    found = []
    for name in _SCANNED:
        path = ROOT / name
        found += (
            sorted(p for p in path.rglob("*") if p.is_file())
            if path.is_dir()
            else [path]
        )
    return [
        path
        for path in found
        if _EXPLAINED not in path.parents
        and path != pathlib.Path(__file__)
        and "__pycache__" not in path.parts
        and ".egg-info" not in str(path)
    ]


def _named(path: pathlib.Path) -> list[int]:
    text = path.read_bytes().decode(errors="ignore")
    return [n for n, line in enumerate(text.splitlines(), 1) if _OTHER.search(line)]


def test_the_scan_finds_another_database() -> None:
    assert _OTHER.search('ARANGO_URL = "http://localhost:8529"')
    assert _OTHER.search("  arangodb:")
    assert _OTHER.search("the AQL before it")
    assert not _OTHER.search("SELECT id FROM nodes WHERE key = %(key)s")
    assert not _OTHER.search("an arrangement of the articles")


def test_nothing_names_another_database() -> None:
    files = _files()
    assert ROOT / "pyproject.toml" in files and SRC / "api" / "app.py" in files
    named = [
        f"{path.relative_to(ROOT)}:{lines}" for path in files if (lines := _named(path))
    ]
    assert named == []


def test_importing_the_package_loads_no_other_driver() -> None:
    code = (
        "import sys, lawgraph.__main__, lawgraph.api.app;"
        "print([m for m in sys.modules if m.split('.')[0] in ('arango', 'pyarango')])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"
