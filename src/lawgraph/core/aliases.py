"""Instrument alias tables: law name -> ``(bwb_id, celex)``."""

from __future__ import annotations

from typing import Any

InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


def normalize_instrument_id(value: Any) -> str | None:
    """Stripped, upper-cased id string; ``None`` for a falsy *value*."""
    return str(value).strip().upper() if value else None
