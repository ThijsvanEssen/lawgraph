"""`lawgraph check` watches the size of the database, run for real on the small test server.

ArangoDB Community stops a server that holds 100 GiB or more (warnings for two days, then two
days read-only, then shut down). The check reports the size every run and fails from the
alert threshold on, well before that.
"""

from __future__ import annotations

import pytest

from lawgraph.commands import check as check_module
from lawgraph.commands.check import check
from lawgraph.db import ArangoStore


def _size_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("database size")]


def test_the_size_is_reported_under_the_threshold(database: str) -> None:
    report = check(ArangoStore(), edges=False)
    assert not _size_lines(report.problems)
    (line,) = _size_lines(report.notes)
    assert "GiB" in line and "alert at 70 GiB" in line


def test_the_size_fails_the_check_from_the_threshold_on(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check_module, "DB_SIZE_ALERT_GIB", 0.0)
    report = check(ArangoStore(), edges=False)
    (line,) = _size_lines(report.problems)
    assert "alert at 0 GiB" in line


def test_the_largest_collections_are_named(database: str) -> None:
    (line,) = _size_lines(check(ArangoStore(), edges=False).notes)
    assert "largest:" in line
