"""Instrument alias tables: law name -> ``(bwb_id, celex)``, abbreviation -> law id."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from lawgraph.core.code_families import CODE_FAMILIES
from lawgraph.core.curated import LISTS
from lawgraph.core.identifiers import is_bwb_id

InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


def curated_abbreviations() -> dict[str, list[str]]:
    """Law id -> the abbreviations kept by hand for it (``curated instrument-abbreviations``)."""
    return {
        law_id.upper(): list((value or {}).get("abbreviations") or [])
        for law_id, value in LISTS["instrument-abbreviations"].entries().items()
    }


def abbreviation_of(
    law_id: str, short_title: str | None, curated: Mapping[str, Sequence[str]]
) -> str | None:
    """The abbreviation an instrument is cited by: the short title of a BWB regulation or
    treaty (its WTI ``afkorting``, ``choose_short_titles``: EVRM), else the first one kept
    by hand for it (``curated instrument-abbreviations``: AVG for 32016R0679; EUR-Lex gives
    an EU act a short title in words, never an abbreviation); None without either."""
    if short_title and is_bwb_id(law_id):
        return short_title
    return next(iter(curated.get(law_id.upper()) or ()), None)


def code_aliases(
    rows: Iterable[Mapping[str, Any]],
    curated: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, str]:
    """Abbreviation, as its source spells it -> the BWB id or CELEX number of the one law it
    stands for.

    *rows* are ``{bwb_id, celex, short_title, aliases}`` of the instruments in the graph;
    *curated* adds abbreviations by law id (``curated instrument-abbreviations``), for the
    laws among *rows* only. The sources rank: a short title, then the other abbreviations of
    the source (the WTI's, ``WvSr`` beside ``Sr``), then the curated ones. An abbreviation is
    decided by the first of them that has it, whatever the others say, and is the law's only
    when one law has it there. Comparison ignores case. A code whose books are regulations of
    their own (``BW``) and an alias that starts with a digit (``6 BW``: the number of a
    citation stands there) are no abbreviation of one law.
    """
    tiers: list[dict[str, dict[str, str]]] = [{}, {}, {}]  # upper -> law id -> spelling
    for row in rows:
        law_id = normalize_instrument_id(row.get("bwb_id") or row.get("celex"))
        if not law_id:
            continue
        sources = (
            [row.get("short_title")],
            row.get("aliases") or [],
            (curated or {}).get(law_id, []),
        )
        for tier, names in zip(tiers, sources, strict=True):
            for name in names:
                spelled = str(name or "").strip()
                key = spelled.upper()
                if key and not key[0].isdigit() and key not in CODE_FAMILIES:
                    tier.setdefault(key, {}).setdefault(law_id, spelled)
    found: dict[str, str] = {}
    decided: set[str] = set()
    for tier in tiers:
        for key, laws in tier.items():
            if key in decided:
                continue
            decided.add(key)
            if len(laws) == 1:
                ((law_id, spelled),) = laws.items()
                found[spelled] = law_id
    return found


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
