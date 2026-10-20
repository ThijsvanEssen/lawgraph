"""Today as a Dutch visitor has it, whatever the clock of the server."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from lawgraph.core import time
from lawgraph.core.ecli import is_valid_ecli
from lawgraph.core.identifiers import has_possible_year
from lawgraph.core.search_stats import SearchTermCounter
from lawgraph.pipelines.retrieve.tk_content import _is_fresh

# New Year's Eve, 23:30 UTC: in the Netherlands already 1 January 2028.
NEW_YEAR_NIGHT = dt.datetime(2027, 12, 31, 23, 30, tzinfo=dt.UTC)


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


SRC = Path(time.__file__).parents[1]

# A day is the Dutch one everywhere in src; a moment is taken with its time zone.
_NOT_A_DUTCH_DAY = ("date.today()", "datetime.now()", "utcnow(", "now(dt.UTC).date()")


def test_every_day_is_the_dutch_one() -> None:
    found = [
        f"{path.relative_to(SRC)}:{n}"
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "time.py" or path.parent.name != "core"
        for n, line in enumerate(path.read_text().splitlines(), start=1)
        if any(call in line for call in _NOT_A_DUTCH_DAY)
    ]
    assert found == []


def test_an_ecli_of_the_new_year_is_valid_on_new_years_night(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "_now", lambda: NEW_YEAR_NIGHT)
    assert is_valid_ecli("ECLI:NL:HR:2028:1")


def test_a_celex_of_next_year_is_possible_on_new_years_night(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "_now", lambda: NEW_YEAR_NIGHT)
    assert has_possible_year("32029R0001")


def test_a_document_ages_on_the_dutch_day(monkeypatch: pytest.MonkeyPatch) -> None:
    # 22:30 UTC on 10 June is 11 June in the Netherlands: a document of 27 May is then
    # 15 days old, past the 14 in which its XML is still on its way.
    monkeypatch.setattr(
        time, "_now", lambda: dt.datetime(2030, 6, 10, 22, 30, tzinfo=dt.UTC)
    )
    assert not _is_fresh("2030-05-27")


def test_a_search_late_in_the_evening_counts_on_the_dutch_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        time, "_now", lambda: dt.datetime(2026, 10, 15, 22, 30, tzinfo=dt.UTC)
    )
    counter = SearchTermCounter()
    counter.add("huurrecht")
    assert list(counter.take()) == ["2026-10-16"]
