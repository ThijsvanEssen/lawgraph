"""Today as a Dutch visitor has it, whatever the clock of the server."""

from __future__ import annotations

import datetime as dt

import pytest

from lawgraph.core import time


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
