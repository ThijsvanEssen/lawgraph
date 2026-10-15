"""What every reader of a TK record uses: the payload and its fields."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

Payload = dict[str, Any]
Record = tuple[str, dict[str, Any]]


def dicts(value: Any) -> Iterator[Payload]:
    """Yield the dicts in *value*, which TK gives as a list, a dict or null."""
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def first_text(payload: Payload, *fields: str) -> str:
    """First non-empty string among *fields*."""
    for field in fields:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def id_of(payload: Payload) -> str:
    return str(payload.get("Id") or "")


def is_deleted(payload: Payload) -> bool:
    """Whether the Kamer deleted the record: it then holds its id and nothing else."""
    return payload.get("Verwijderd") is True


def distinct(values: Iterable[str]) -> list[str]:
    """Non-empty values, deduplicated, in first-seen order."""
    return list(dict.fromkeys(value for value in values if value))
