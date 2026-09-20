"""Pure accessors for ``raw_sources`` records (as read back from the store)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def group_by_kind(
    rows: list[dict[str, Any]], *, kinds: Iterable[str]
) -> dict[str, list[dict[str, Any]]]:
    """Group raw records by their kind, keeping an entry for each requested kind."""
    grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in kinds}
    for row in rows:
        kind = row.get("kind")
        if kind in grouped:
            grouped[kind].append(row)
    return grouped


def payload_json(raw: dict[str, Any]) -> dict[str, Any]:
    """The record's JSON payload if it is an object, else ``{}``."""
    payload = raw.get("payload_json")
    return payload if isinstance(payload, dict) else {}


def payload_text(raw: dict[str, Any]) -> str | None:
    """The record's text payload if it is a string, else ``None``."""
    payload = raw.get("payload_text")
    return payload if isinstance(payload, str) else None


def meta(raw: dict[str, Any]) -> dict[str, Any]:
    """The record's ``meta`` if it is an object, else ``{}``."""
    value = raw.get("meta")
    return value if isinstance(value, dict) else {}
