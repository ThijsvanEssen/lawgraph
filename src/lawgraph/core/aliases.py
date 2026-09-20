"""Instrument alias tables: law name -> ``(bwb_id, celex)``."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


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
