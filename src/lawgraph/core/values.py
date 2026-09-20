"""Small pure helpers for picking values out of loosely-typed payloads."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def first_str(values: Iterable[Any], *, skip_blank: bool = False) -> str | None:
    """First non-``None`` value of *values* as a string, or ``None``.

    By default the value is returned as ``str(value)`` untouched, so an empty
    string counts as a value. With ``skip_blank=True`` values are stripped and
    blank ones are skipped, so the result is never empty.
    """
    for value in values:
        if value is None:
            continue
        text = str(value)
        if not skip_blank:
            return text
        text = text.strip()
        if text:
            return text
    return None


def first_text_prop(props: dict[str, Any], *keys: str) -> str | None:
    """First non-blank string found under *keys* in *props* (returned unstripped)."""
    for key in keys:
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def next_page_link(page: Any, key: str | None) -> str | None:
    """Stripped pagination next-link stored under *key* in a page payload, if any."""
    if key is None or not isinstance(page, dict):
        return None
    candidate = page.get(key)
    if isinstance(candidate, str):
        return candidate.strip() or None
    return None
