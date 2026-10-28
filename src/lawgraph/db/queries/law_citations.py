"""The judgments that cite a law, kept per law in columns, so that a page, a sort, a year, a
tier or an area of law is read from memory and not counted anew from ``lg_cited_by``.

The Awb is 600,000 citations by 300,000 judgments: grouped per judgment that took 24 to 27 s
cold on prod, for every page and every filter the explorer asked (28 Oct). Here that is done
once per law (``LawCitations``, built from one row per judgment); the page of judgments itself
is read by their ids. The columns share their strings and tuples, and the laws together keep
``LAW_CITATIONS_ROWS`` rows at most."""

from __future__ import annotations

import math
import threading
from array import array
from collections import Counter, OrderedDict
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from lawgraph.config.settings import LAW_CITATIONS_ROWS

# How a judgment is read: its id, the number of articles of the law it cites, its date,
# tier, ``inbound_citation_count`` and main areas of law (one row of ``cites`` in
# ``instruments._law_citations``).
Row = Mapping[str, Any]


@dataclass(frozen=True)
class Counts:
    """The judgments under a filter and the facets of the explorer: ``total``, and ``years``,
    ``tiers`` and ``areas`` as ``[{value, count}]`` (each counted under the other two
    filters, whatever its own)."""

    total: int
    years: list[dict[str, Any]]
    tiers: list[dict[str, Any]]
    areas: list[dict[str, Any]]


@dataclass(frozen=True)
class Reading:
    """What one request reads of a law: the ids of its page, in order, and the counts."""

    ids: list[str]
    counts: Counts


class _Columns:
    """The judgments of a law, one position each, in the order of their ids."""

    def __init__(self, rows: Iterable[Row]) -> None:
        shared: dict[Any, Any] = {}
        self.ids: list[str] = []
        self.dates: list[str | None] = []
        self.years: list[str | None] = []
        self.tiers: list[str | None] = []
        self.areas: list[tuple[str, ...]] = []
        self.cited_count = array("I")
        self.cited = array("d")
        # (year, tier, areas) -> judgments: the counts of every filter, in a few thousand
        self.groups: Counter[tuple[str | None, str | None, tuple[str, ...]]] = Counter()
        for row in rows:
            date = shared.setdefault(row["date_eff"], row["date_eff"])
            year = shared.setdefault(
                date[:4] if date else None, date[:4] if date else None
            )
            tier = shared.setdefault(row["tier"], row["tier"])
            areas = tuple(row["areas"] or ())
            areas = shared.setdefault(areas, areas)
            self.ids.append(row["judgment_id"])
            self.dates.append(date)
            self.years.append(year)
            self.tiers.append(tier)
            self.areas.append(areas)
            self.cited_count.append(row["cited_count"])
            cited = row["cited"]
            self.cited.append(math.nan if cited is None else cited)
            self.groups[year, tier, areas] += 1
        self.orders: dict[str, array[int]] = {}

    def order(self, sort: str) -> array[int]:
        """The positions in the order of *sort* (``date``, ``cited``, ``citation_count``):
        the newest first, the most cited articles of the law first or the most cited judgment
        first, each then the newest; the id (the order of the positions) settles ties."""
        found = self.orders.get(sort)
        if found is None:
            positions = list(range(len(self.ids)))
            # stable sorts, the last one the most important; a missing value comes last
            positions.sort(
                key=lambda i: (self.dates[i] is not None, self.dates[i] or ""),
                reverse=True,
            )
            if sort == "cited":
                positions.sort(key=self.cited_count.__getitem__, reverse=True)
            elif sort == "citation_count":
                positions.sort(key=self._cited_key, reverse=True)
            found = self.orders[sort] = array("I", positions)
        return found

    def _cited_key(self, i: int) -> tuple[bool, float]:
        cited = self.cited[i]
        return (not math.isnan(cited), 0.0 if math.isnan(cited) else cited)


class LawCitations:
    """The judgments that cite a law (every article of it), read by ``read``. It can be
    dropped (``release``) when the laws together keep more than ``LAW_CITATIONS_ROWS``."""

    def __init__(self, rows: Iterable[Row]) -> None:
        self._columns: _Columns | None = _Columns(rows)
        self.size = len(self._columns.ids)
        self._lock = threading.Lock()

    def release(self) -> None:
        """Drop the columns; a request that has them goes on with them."""
        self._columns = None

    def read(
        self,
        sort: str,
        limit: int,
        offset: int,
        year: str | None,
        tiers: tuple[str, ...],
        area: str | None,
    ) -> Reading | None:
        """The page (*limit* ids from *offset*) of the judgments under *year*, of any of
        *tiers* and in the area of law *area* (each None or empty: any), in the order of
        *sort*, and the counts; None when the law was dropped."""
        columns = self._columns
        if columns is None:
            return None
        with self._lock:
            order = columns.order(sort)
        return Reading(
            _page(columns, order, limit, offset, year, set(tiers), area),
            _counts(columns, year, set(tiers), area),
        )


def _page(
    columns: _Columns,
    order: array[int],
    limit: int,
    offset: int,
    year: str | None,
    tiers: set[str],
    area: str | None,
) -> list[str]:
    ids: list[str] = []
    seen = 0
    for i in order:
        if year is not None and columns.years[i] != year:
            continue
        if tiers and columns.tiers[i] not in tiers:
            continue
        if area is not None and area not in columns.areas[i]:
            continue
        if seen >= offset:
            ids.append(columns.ids[i])
            if len(ids) >= limit:
                break
        seen += 1
    return ids


def _counts(
    columns: _Columns, year: str | None, tiers: set[str], area: str | None
) -> Counts:
    total = 0
    years: Counter[str | None] = Counter()
    per_tier: Counter[str | None] = Counter()
    per_area: Counter[str] = Counter()
    for (y, t, areas), n in columns.groups.items():
        year_ok = year is None or y == year
        tier_ok = not tiers or t in tiers
        area_ok = area is None or area in areas
        if tier_ok and area_ok:
            years[y] += n
        if year_ok and area_ok:
            per_tier[t] += n
        if year_ok and tier_ok:
            for value in areas:
                per_area[value] += n
            if area_ok:
                total += n
    return Counts(
        total,
        [
            {"value": v, "count": n}
            for v, n in sorted(
                years.items(), key=lambda p: (p[0] is not None, p[0] or "")
            )
        ],
        [
            {"value": v, "count": n}
            for v, n in sorted(
                per_tier.items(), key=lambda p: (-p[1], p[0] is None, p[0] or "")
            )
        ],
        [
            {"value": v, "count": n}
            for v, n in sorted(per_area.items(), key=lambda p: (-p[1], p[0]))
        ],
    )


# The laws kept, the one used longest ago first, and per law how often it was dropped (its
# key for the cache of ``version_cache.lasting`` carries it, so that a dropped law is built
# again and not served empty).
_kept: OrderedDict[Hashable, LawCitations] = OrderedDict()
_dropped: Counter[Hashable] = Counter()
_lock = threading.Lock()


def generation(law: Hashable) -> int:
    """How often the index of *law* was dropped."""
    return _dropped[law]


def keep(law: Hashable, index: LawCitations) -> LawCitations:
    """Count *index* of *law* among the laws kept, and drop the laws used longest ago while
    they hold more than ``LAW_CITATIONS_ROWS`` together (never *index*)."""
    with _lock:
        _kept.pop(law, None)
        _kept[law] = index
        while (
            len(_kept) > 1 and sum(i.size for i in _kept.values()) > LAW_CITATIONS_ROWS
        ):
            oldest, dropped = next(iter(_kept.items()))
            del _kept[oldest]
            dropped.release()
            _dropped[oldest] += 1
    return index


def used(law: Hashable) -> None:
    """*law* was read just now."""
    with _lock:
        if law in _kept:
            _kept.move_to_end(law)


def forget() -> None:
    """Forget every law kept (the tests)."""
    with _lock:
        _kept.clear()
        _dropped.clear()
