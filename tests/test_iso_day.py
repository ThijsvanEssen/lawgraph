"""``iso_day``: the day of a date, and of a moment in UTC (as ``iso_timestamp``)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from lawgraph.core.time import iso_day


def test_a_date_is_its_own_day_and_none_stays_none() -> None:
    assert iso_day(dt.date(2026, 10, 15)) == "2026-10-15"
    assert iso_day(None) is None


def test_a_moment_gives_its_day_in_utc() -> None:
    assert iso_day(dt.datetime(2026, 10, 15, 0, 30)) == "2026-10-15"  # naive: UTC
    assert iso_day(dt.datetime(2026, 10, 15, 23, 30, tzinfo=dt.UTC)) == "2026-10-15"
    # 00:30 in Amsterdam (CEST) is 22:30 UTC the day before: that day stays in
    cest = dt.datetime(2026, 10, 15, 0, 30, tzinfo=ZoneInfo("Europe/Amsterdam"))
    assert iso_day(cest) == "2026-10-14"
