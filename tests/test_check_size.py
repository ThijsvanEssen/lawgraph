"""``lawgraph check`` reports the size of the database and fails from the alert size on."""

from __future__ import annotations

import pytest

from lawgraph.commands import check as check_module
from lawgraph.commands.check import GIB, Report, _check_size


class _Store:
    def __init__(self, size: int) -> None:
        self.size = size

    def database_size(self) -> int:
        return self.size

    def collection_sizes(self) -> dict[str, int]:
        return {"edges": 3 * GIB, "articles": 2 * GIB, "nodes": GIB, "cases": GIB // 2}


def _report(size: int, monkeypatch: pytest.MonkeyPatch) -> Report:
    monkeypatch.setattr(check_module, "DB_SIZE_ALERT_GIB", 10.0)
    report = Report()
    _check_size(_Store(size), report)  # type: ignore[arg-type]
    return report


def test_under_the_threshold_the_size_is_a_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(9 * GIB, monkeypatch)
    assert report.problems == []
    assert report.notes == [
        "database size 9.00 GiB (alert at 10 GiB); largest: edges 3.00 GiB, "
        "articles 2.00 GiB, nodes 1.00 GiB"
    ]


def test_from_the_threshold_on_the_size_is_a_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report(10 * GIB, monkeypatch)
    assert report.notes == []
    assert report.problems == [
        "database size 10.00 GiB (alert at 10 GiB); largest: edges 3.00 GiB, "
        "articles 2.00 GiB, nodes 1.00 GiB. Make it smaller before the data volume fills."
    ]
