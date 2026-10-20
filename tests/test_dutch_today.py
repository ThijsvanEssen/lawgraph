"""Today as a Dutch visitor has it, whatever the clock of the server."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from lawgraph.core import time
from lawgraph.core.search_stats import SearchTermCounter


@pytest.mark.parametrize(
    ("utc", "today"),
    [
        # summer time (UTC+2): from 22:00 UTC it is the next day
        (dt.datetime(2026, 10, 15, 21, 59, tzinfo=dt.UTC), dt.date(2026, 10, 15)),
        (dt.datetime(2026, 10, 15, 22, 30, tzinfo=dt.UTC), dt.date(2026, 10, 16)),
        # winter time (UTC+1): from 23:00 UTC
        (dt.datetime(2026, 12, 1, 22, 59, tzinfo=dt.UTC), dt.date(2026, 12, 1)),
        (dt.datetime(2026, 12, 1, 23, 0, tzinfo=dt.UTC), dt.date(2026, 12, 2)),
    ],
)
def test_today_is_the_date_in_the_netherlands(
    monkeypatch: pytest.MonkeyPatch, utc: dt.datetime, today: dt.date
) -> None:
    monkeypatch.setattr(time, "_now", lambda: utc)
    assert time.dutch_today() == today


# The code a visitor's day reaches: the routes, their queries, the commands that write what
# they read (feed events, search statistics, sitemaps) and the counter of the searches.
_VISITOR_DAY = [
    *(Path(time.__file__).parents[1] / part for part in ("api", "db", "commands")),
    Path(time.__file__).parent / "search_stats.py",
]


def test_a_visitors_day_is_the_dutch_one() -> None:
    files = [p for root in _VISITOR_DAY for p in sorted(root.rglob("*.py")) or [root]]
    found = [
        f"{path.name}:{n}"
        for path in files
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if "date.today()" in line
    ]
    assert found == []


def test_a_search_late_in_the_evening_counts_on_the_dutch_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        time, "_now", lambda: dt.datetime(2026, 10, 15, 22, 30, tzinfo=dt.UTC)
    )
    counter = SearchTermCounter()
    counter.add("huurrecht")
    assert list(counter.take()) == ["2026-10-16"]
