"""Regulations that follow one another under one name, grouped as a series.

The BWB gives a regulation that is renewed every year (a mandaatbesluit, a tariff regulation)
a regulation of its own with its own ``BWBR`` id; its toestanden and its WTI (its head, the
only part kept) name no predecessor, so no relation says that ``Mandaatbesluit DT&V 2022`` follows
``Mandaatbesluit DT&V 2020``. A series is therefore a **heuristic**: regulations of one kind
whose citation titles are the same once their years are taken out, at least two of them, and a
year in each. They are ordered by the day they came into force.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

# 2020, 2022-2023, 2022/23, 2022 - 2023
_YEARS = re.compile(r"\b(?:19|20)\d{2}(?:\s*[-–/]\s*(?:19|20)?\d{2,4})?\b")
_NOT_WORD = re.compile(r"[^\w&]+")
_SLUG = re.compile(r"[^a-z0-9]+")

# What the series says of how it was made.
BASIS_TITLE_YEAR = "title_year"


@dataclass(frozen=True)
class Series:
    id: str
    position: int
    size: int
    basis: str = BASIS_TITLE_YEAR


def series_stem(citation_title: str | None) -> str | None:
    """The title without its years (``mandaatbesluit dt&v``); None when it has no year or
    nothing is left of it."""
    title = (citation_title or "").casefold()
    stem, years = _YEARS.subn(" ", title)
    stem = _NOT_WORD.sub(" ", stem).strip()
    return stem if years and len(stem) > 2 else None


def series_of(
    instruments: Iterable[tuple[str, str | None, str | None, str | None]],
) -> dict[str, Series]:
    """The series of *instruments* (``(key, citation title, kind, day in force)``), by key:
    only an instrument with a sibling is in one. The position counts from 1 by the day in
    force, the key settling a tie."""
    groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key, title, kind, in_force in instruments:
        stem = series_stem(title)
        if stem:
            groups[f"{kind or ''} {stem}"].append((str(in_force or "")[:10], key))
    found: dict[str, Series] = {}
    for name, members in groups.items():
        if len(members) < 2:
            continue
        series_id = _SLUG.sub("-", name.replace("&", " en ").strip()).strip("-")
        for position, (_, key) in enumerate(sorted(members), start=1):
            found[key] = Series(series_id, position, len(members))
    return found
