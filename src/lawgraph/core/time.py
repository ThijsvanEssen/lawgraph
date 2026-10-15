"""Helper functions for formatting pipeline timestamps."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

# The time of the Netherlands, whose day a visitor's page asks (the explorer's ``vandaag``).
DUTCH_TIME = ZoneInfo("Europe/Amsterdam")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def dutch_today() -> dt.date:
    """Today in the Netherlands, also on a server whose clock runs on UTC: from 22:00 UTC
    in summer (23:00 in winter) the next day."""
    return _now().astimezone(DUTCH_TIME).date()


def iso_timestamp(value: dt.datetime | None) -> str | None:
    """Return an ISO 8601 string in UTC for the provided datetime, or None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    iso_value = value.astimezone(dt.UTC).isoformat()
    if iso_value.endswith("+00:00"):
        return iso_value.replace("+00:00", "Z")
    return iso_value


def iso_day(value: dt.date | None) -> str | None:
    """A day as the queries take it, ``YYYY-MM-DD``; None stays None. A moment gives its
    day in UTC (a naive one taken as UTC), as ``iso_timestamp`` reads it: the ``since`` of a
    filter on a date prop, which compared with a timestamp would sort before every
    timestamp of its own day."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return str(iso_timestamp(value))[:10]
    return value.isoformat()


def utc_now_iso() -> str:
    """Now in UTC to the second, as ``iso_timestamp`` writes it: the stamp of a write."""
    return str(iso_timestamp(_now().replace(microsecond=0)))


def describe_since(value: dt.datetime | None) -> str:
    """Return a human-friendly description of the since filter used for logging."""
    return iso_timestamp(value) or "full history"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_date(val: Any) -> str | None:
    """Extract a YYYY-MM-DD string from a date/datetime value or OData datetime string."""
    if not val:
        return None
    s = str(val)
    if "T" in s:
        s = s.split("T")[0]
    elif len(s) >= 10:
        s = s[:10]
    return s if _DATE_RE.match(s) else None


def odata_datetime(value: dt.datetime) -> str:
    """Format a datetime for an OData filter: ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, no fraction)."""
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC)
    return value.replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def sortable_date(value: str | None) -> dt.date:
    """Parse an ISO date for sorting; missing or malformed values sort first."""
    if not value:
        return dt.date.min
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return dt.date.min


def strip_time_component(value: str | None) -> str | None:
    """Return only the date portion of an ISO 8601 string (drops time and timezone)."""
    if not value:
        return None
    s = str(value)
    return s.split("T")[0] if "T" in s else s


RELATIVE_SINCE_OVERLAP = dt.timedelta(hours=6)


_RELATIVE_SINCE = re.compile(r"^(\d+)([dhm])$")
_RELATIVE_UNIT = {"d": "days", "h": "hours", "m": "minutes"}


def parse_since(value: str | None) -> dt.datetime | None:
    """Parse a --since CLI argument into a UTC datetime.

    Accepts ISO 8601 strings (e.g. ``2024-01-01``) or a relative window: ``7d`` (days),
    ``2h`` (hours) or ``90m`` (minutes).  Returns ``None`` when *value* is empty.
    """
    if not value:
        return None
    value = value.strip()
    if relative := _RELATIVE_SINCE.match(value):
        window = dt.timedelta(**{_RELATIVE_UNIT[relative[2]]: int(relative[1])})
        if relative[2] == "d":
            # A run every N days with `--since Nd` has no slack at all: a run that starts a
            # minute late, or a source that indexes a change an hour after it was made,
            # leaves a hole that no later run looks into. Everything is an upsert, so
            # overlap is free. A window in hours or minutes is a poll's: it is taken as it
            # is, and the poll chooses it wider than the time between its runs.
            window += RELATIVE_SINCE_OVERLAP
        return dt.datetime.now(dt.UTC) - window
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.UTC)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Cannot parse --since value '{value}'.") from exc


def format_duration(seconds: float) -> str:
    """``12s``, ``4m12s`` or ``1h02m``: how long a step took."""
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


# The first day of every period and the last day of one that has not ended: they sort
# before and after every real day.
OPEN_START, OPEN_END = "0000-01-01", "9999-12-31"


@dataclass(frozen=True)
class Period:
    """Days *start* to *end*, both inclusive; *end* None: still running."""

    start: str
    end: str | None

    @classmethod
    def of(
        cls, row: Mapping[str, Any], start: str = "from_date", end: str = "to_date"
    ) -> Period | None:
        """The period of *row* from its field *start* to its field *end* (days, or
        timestamps read as their day); None without a start."""
        first = str(row.get(start) or "")[:10]
        last = str(row.get(end) or "")[:10] or None
        return cls(first, last) if first else None

    def covers(self, day: str) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


def covers(
    row: Mapping[str, Any], day: str, start: str = "from_date", end: str = "to_date"
) -> bool:
    """The period of *row* (``Period.of``) holds *day*; a row without a start holds none.
    The rule of the SQL ``period_holds``."""
    period = Period.of(row, start, end)
    return period is not None and period.covers(day)


def shift_day(day: str, days: int) -> str:
    """The ISO day *days* after *day* (before it when negative)."""
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


def day_before(day: str) -> str:
    """The ISO day before *day*."""
    return shift_day(day, -1)
