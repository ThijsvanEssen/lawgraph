"""Moments and windows (``core/time.py``): OData datetimes, sortable dates and ``--since``."""

from __future__ import annotations

import datetime as dt

import pytest

from lawgraph.core.time import odata_datetime, sortable_date


def test_format_odata_datetime() -> None:
    fmt = odata_datetime
    assert fmt(dt.datetime(2024, 1, 2, 3, 4, 5, 999)) == "2024-01-02T03:04:05Z"
    aware = dt.datetime(2024, 1, 2, 5, 4, 5, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert fmt(aware) == "2024-01-02T03:04:05Z"


def test_bwb_date_for_sort() -> None:
    fn = sortable_date
    assert fn(None) == dt.date.min
    assert fn("") == dt.date.min
    assert fn("garbage") == dt.date.min
    assert fn("2020-02-03") == dt.date(2020, 2, 3)
    assert fn("9999-12-31") == dt.date(9999, 12, 31)


def test_a_relative_since_overlaps_with_the_run_before_it() -> None:
    """`--since 1d` every day has no slack: a late start or a late index leaves a hole."""
    import datetime as dt

    from lawgraph.core.time import RELATIVE_SINCE_OVERLAP, parse_since

    now = dt.datetime.now(dt.UTC)
    since = parse_since("1d")
    assert since is not None
    assert abs(
        (now - since) - (dt.timedelta(days=1) + RELATIVE_SINCE_OVERLAP)
    ) < dt.timedelta(seconds=5)
    assert parse_since("2024-01-01") == dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("value", "window"),
    [("2h", {"hours": 2}), ("90m", {"minutes": 90}), (" 3h ", {"hours": 3})],
)
def test_a_poll_window_in_hours_or_minutes_is_taken_as_it_is(value, window) -> None:
    """A poll every 30 minutes with `--since 2h` overlaps by its own window; six hours more
    would make every poll read a working day."""
    import datetime as dt

    from lawgraph.core.time import parse_since

    now = dt.datetime.now(dt.UTC)
    since = parse_since(value)
    assert since is not None
    assert abs((now - since) - dt.timedelta(**window)) < dt.timedelta(seconds=5)


@pytest.mark.parametrize("value", ["2x", "h", "-2h", "2.5h", "2hours"])
def test_a_since_that_is_no_window_or_date_is_refused(value) -> None:
    from lawgraph.core.time import parse_since

    with pytest.raises(ValueError, match="Cannot parse --since"):
        parse_since(value)
