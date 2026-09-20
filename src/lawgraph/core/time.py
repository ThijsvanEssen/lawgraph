"""Helper functions for formatting pipeline timestamps."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any


def iso_timestamp(value: dt.datetime | None) -> str | None:
    """Return an ISO 8601 string in UTC for the provided datetime, or None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    iso_value = value.astimezone(dt.timezone.utc).isoformat()
    if iso_value.endswith("+00:00"):
        return iso_value.replace("+00:00", "Z")
    return iso_value


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
        value = value.astimezone(dt.timezone.utc)
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


def parse_since(value: str | None) -> dt.datetime | None:
    """Parse a --since CLI argument into a UTC datetime.

    Accepts ISO 8601 strings (e.g. ``2024-01-01``) or relative shorthand
    like ``7d`` (last 7 days).  Returns ``None`` when *value* is empty.
    """
    if not value:
        return None
    value = value.strip()
    if value.endswith("d") and value[:-1].isdigit():
        return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(value[:-1]))
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
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
