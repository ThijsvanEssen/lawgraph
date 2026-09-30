"""Instrument alias tables: law name -> ``(bwb_id, celex)``, abbreviation -> law id."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from lawgraph.core.code_families import CODE_FAMILIES
from lawgraph.core.curated import LISTS

InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


def curated_abbreviations() -> dict[str, list[str]]:
    """Law id -> the abbreviations kept by hand for it (``curated instrument-abbreviations``)."""
    return {
        law_id.upper(): list((value or {}).get("abbreviations") or [])
        for law_id, value in LISTS["instrument-abbreviations"].entries().items()
    }


def code_aliases(
    rows: Iterable[Mapping[str, Any]],
    curated: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    """Abbreviation (upper case) -> the BWB id or CELEX number of the one law it stands for.

    *rows* are ``{bwb_id, celex, short_title, aliases}`` of the instruments in the graph;
    *curated* adds abbreviations by law id (``curated instrument-abbreviations``), for the
    laws among *rows* only. A short title comes first: an abbreviation that is the short
    title of one law is that law's, whatever other laws list it among their aliases (the
    WTI abbreviations, ``WvSr`` beside ``Sr``). Of the other abbreviations only those that
    one law claims count. A code whose books are regulations of their own (``BW``) and an
    alias that starts with a digit (``6 BW``: the number of a citation stands there) are no
    abbreviation of one law.
    """
    short: dict[str, set[str]] = {}
    other: dict[str, set[str]] = {}
    for row in rows:
        law_id = normalize_instrument_id(row.get("bwb_id") or row.get("celex"))
        if not law_id:
            continue
        names = [*(row.get("aliases") or []), *(curated or {}).get(law_id, [])]
        for tier, candidates in ((short, [row.get("short_title")]), (other, names)):
            for name in candidates:
                key = str(name or "").strip().upper()
                if key and not key[0].isdigit() and key not in CODE_FAMILIES:
                    tier.setdefault(key, set()).add(law_id)
    found: dict[str, str] = {}
    for tier in (short, other):
        for key, laws in tier.items():
            if key not in found and len(laws) == 1:
                found[key] = next(iter(laws))
    return {
        key: law
        for key, law in found.items()
        if len(short.get(key, ())) <= 1  # a short title two laws share is no one's
    }


def normalize_instrument_id(value: Any) -> str | None:
    """Stripped, upper-cased id string; ``None`` for a falsy *value*."""
    return str(value).strip().upper() if value else None


_KEY_LENGTH = 8


def _is_word(char: str) -> bool:
    return char.isalnum() or char == "_"


def _lowered(text: str) -> str:
    """*text* in lower case with every character kept in place."""
    lowered = text.lower()
    if len(lowered) == len(text):
        return lowered
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


class AliasMatcher:
    """Finds law names in a text in one pass over the text, however many names there are.

    A name matches as a whole, case-insensitively: not inside a longer word. The names are
    indexed by their first characters, so a text is looked at once per word start instead of
    once per name.
    """

    def __init__(self, labels: Iterable[str]) -> None:
        # first characters -> [(order, lowered label)]; one table per key length, because
        # a label shorter than ``_KEY_LENGTH`` is its own key.
        self._tables: dict[int, dict[str, list[tuple[int, str]]]] = {}
        for order, label in enumerate(labels):
            lowered = _lowered(label)
            if not lowered:
                continue
            key = lowered[:_KEY_LENGTH]
            self._tables.setdefault(len(key), {}).setdefault(key, []).append(
                (order, lowered)
            )

    def first_matches(self, text: str) -> list[tuple[int, int, int]]:
        """``(label order, start, end)`` of the first match of each label, in label order."""
        lowered = _lowered(text)
        size = len(lowered)
        found: dict[int, tuple[int, int]] = {}
        for start in range(size):
            if start and _is_word(lowered[start - 1]):
                continue
            for key_length, table in self._tables.items():
                candidates = table.get(lowered[start : start + key_length])
                if not candidates:
                    continue
                for order, label in candidates:
                    end = start + len(label)
                    if (
                        order not in found
                        and lowered.startswith(label, start)
                        and not (end < size and _is_word(lowered[end]))
                    ):
                        found[order] = (start, end)
        return [(order, *found[order]) for order in sorted(found)]
