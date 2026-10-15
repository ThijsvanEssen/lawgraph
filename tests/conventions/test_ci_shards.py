"""The database shards of ``.github/workflows/tests.yaml`` run every file of ``tests/pg`` and
``tests/integration`` once, and a file whose tests share a worker (``xdist_group``) in a shard
that keeps them together (``dist: loadgroup``; worksteal ignores the group).
"""

from __future__ import annotations

from typing import Any

import yaml

from tests.paths import TESTS

ROOT = TESTS.parent
SHARDS: list[dict[str, Any]] = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "tests.yaml").read_text(encoding="utf-8")
)["jobs"]["database-shard"]["strategy"]["matrix"]["include"]
DATABASE_TESTS = sorted(
    p.relative_to(ROOT).as_posix()
    for folder in ("pg", "integration")
    for p in (TESTS / folder).glob("test_*.py")
)


def _files(shard: dict[str, Any]) -> list[str]:
    """What the shell expands the patterns of ``tests:`` to."""
    return [
        p.relative_to(ROOT).as_posix()
        for pattern in shard["tests"].split()
        for p in ROOT.glob(pattern)
    ]


def test_every_database_test_file_is_in_one_shard() -> None:
    runs = {
        name: [s["shard"] for s in SHARDS if name in _files(s)]
        for name in DATABASE_TESTS
    }
    assert DATABASE_TESTS
    assert {name: shards for name, shards in runs.items() if len(shards) != 1} == {}


def test_every_pattern_finds_a_file() -> None:
    empty = [
        (s["shard"], pattern)
        for s in SHARDS
        for pattern in s["tests"].split()
        if not list(ROOT.glob(pattern))
    ]
    assert empty == []


def test_a_grouped_file_runs_in_a_loadgroup_shard() -> None:
    grouped = [
        name
        for name in DATABASE_TESTS
        if "xdist_group" in (ROOT / name).read_text(encoding="utf-8")
    ]
    elsewhere = [
        (name, s["shard"])
        for s in SHARDS
        if s.get("dist") != "loadgroup"
        for name in _files(s)
        if name in grouped
    ]
    assert grouped
    assert elsewhere == []
