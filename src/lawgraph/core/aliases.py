"""Pure parsing of instrument alias tables (name -> ``(bwb_id, celex)``)."""

from __future__ import annotations

from typing import Any

from lawgraph.core.identifiers import is_bwb_id

InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


def normalize_instrument_id(value: Any) -> str | None:
    """Stripped, upper-cased id string; ``None`` for a falsy *value*."""
    return str(value).strip().upper() if value else None


def parse_instrument_aliases(raw: dict[Any, Any]) -> InstrumentAliasMap:
    """Parse a dict of instrument alias entries into a normalised alias map.

    Accepts values in several forms:
    - a ``(bwb_id, celex)`` tuple (passed through as is)
    - a dict with ``bwb_id`` and/or ``celex`` keys
    - a scalar string (BWB id -> bwb_id, anything else -> celex)

    Entries with a blank alias, or a blank scalar value, are dropped.
    """
    aliases: InstrumentAliasMap = {}
    for alias, value in raw.items():
        label = str(alias or "").strip()
        if not label:
            continue
        if isinstance(value, tuple) and len(value) == 2:
            aliases[label] = value
        elif isinstance(value, dict):
            aliases[label] = (
                normalize_instrument_id(value.get("bwb_id")),
                normalize_instrument_id(value.get("celex")),
            )
        else:
            scalar = str(value or "").strip()
            if not scalar:
                continue
            if is_bwb_id(scalar):
                aliases[label] = (scalar.upper(), None)
            else:
                aliases[label] = (None, scalar.upper())
    return aliases
