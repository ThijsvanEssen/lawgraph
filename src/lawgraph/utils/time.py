"""Helper functions for formatting pipeline timestamps."""

from __future__ import annotations

import datetime as dt


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
