"""Where an article version stands on a day: its place among the articles of the law and the
divisions around it, from every toestand that holds it.

A version (``stam-id`` + ``versie-id``) outlives the toestand it was read from: articles are
inserted before it, it moves to another division, a division is renamed. So both are taken
from all toestanden, which come in no order:

* ``position``: the versions of a law in one order in which the versions of each toestand
  keep theirs (``Order``); sorted by it, the versions in force on a day are in the
  order of that day's toestand;
* ``breadcrumb``: the divisions of the first toestand that holds the version, and
  ``breadcrumb_changes`` the days from which the version stood under other ones
  (``[{from, breadcrumb}]``, oldest first; most versions have none).

A run with ``--since`` reads only the new toestanden: it starts from what an earlier run
stored for each law it reads (``seed``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from lawgraph.core.bwb_xml import Crumb

Crumbs = tuple[Crumb, ...]


class Order:
    """The versions of a law in one order in which the versions of each toestand keep
    theirs. Kept as links, so adding a toestand costs the same in a law of a hundred versions
    as in one of a hundred thousand."""

    def __init__(self) -> None:
        self._next: dict[str | None, str | None] = {None: None}  # None: the start
        self._last: str | None = None

    def __contains__(self, key: str) -> bool:
        return key in self._next

    def __iter__(self) -> Iterator[str]:
        key = self._next[None]
        while key is not None:
            yield key
            key = self._next[key]

    def append(self, key: str) -> None:
        """Add *key* at the end, unless it is in the order."""
        if key not in self._next:
            self._insert_after(self._last, key)

    def merge(self, sequence: Iterable[str]) -> None:
        """Add the keys of *sequence* that the order lacks, each run of them right after the
        key before it in *sequence* (first when there is none), so the keys of *sequence*
        keep their order."""
        previous: str | None = None
        for key in sequence:
            if key not in self._next:
                self._insert_after(previous, key)
            previous = key

    def _insert_after(self, previous: str | None, key: str) -> None:
        self._next[key] = self._next[previous]
        self._next[previous] = key
        if self._next[key] is None:
            self._last = key


def _crumbs(stored: Iterable[Mapping[str, Any]] | None) -> Crumbs:
    return tuple(
        Crumb(type=c.get("type") or "", label=c.get("label"), title=c.get("title"))
        for c in stored or ()
    )


def _stored_points(row: Mapping[str, Any]) -> list[tuple[str, Crumbs]]:
    """The breadcrumbs an earlier run stored, as (from, crumbs); the first from ``""``, the
    start of the version (none when it stored no breadcrumb: a law without divisions)."""
    points = [("", _crumbs(row["breadcrumb"]))] if row.get("breadcrumb") else []
    points += [
        (change.get("from") or "", _crumbs(change.get("breadcrumb")))
        for change in row.get("breadcrumb_changes") or []
    ]
    return points


def _serialised(crumbs: Crumbs) -> list[dict[str, Any]] | None:
    return [crumb.to_dict() for crumb in crumbs] or None


class Places:
    """The order of the versions of each law and the breadcrumbs of each version, gathered
    over the toestanden of one run."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        # version -> {breadcrumb: the first toestand start under it}
        self._first: dict[str, dict[Crumbs, str]] = {}
        self._stored: dict[str, list[tuple[str, Crumbs]]] = {}
        self._interned: dict[Crumbs, Crumbs] = {}

    def __contains__(self, bwb_id: str) -> bool:
        return bwb_id in self._orders

    def seed(self, bwb_id: str, rows: Iterable[Mapping[str, Any]]) -> None:
        """What an earlier run stored for the versions of *bwb_id*, in their stored order:
        ``{key, breadcrumb, breadcrumb_changes}``."""
        order = self._orders.setdefault(bwb_id, Order())
        for row in rows:
            order.append(row["key"])
            self._stored[row["key"]] = _stored_points(row)

    def add(
        self, bwb_id: str, start: str, versions: Iterable[tuple[str, Crumbs]]
    ) -> None:
        """The versions of the toestand of *bwb_id* from *start*, in its order, each with
        its breadcrumb there."""
        versions = list(versions)
        self._orders.setdefault(bwb_id, Order()).merge(key for key, _ in versions)
        for key, crumbs in versions:
            crumbs = self._interned.setdefault(crumbs, crumbs)
            first = self._first.setdefault(key, {})
            if crumbs not in first or start < first[crumbs]:
                first[crumbs] = start

    def positions(self, bwb_id: str) -> dict[str, int]:
        """The position of each version of *bwb_id* in the merged order."""
        return {key: index for index, key in enumerate(self._orders.get(bwb_id, ()))}

    def breadcrumbs(self, key: str) -> dict[str, Any] | None:
        """``breadcrumb`` and ``breadcrumb_changes`` of a version read in this run, else
        None: the breadcrumbs of this run added to those stored before it."""
        first = self._first.get(key)
        if first is None:
            return None
        points = dict(
            self._stored.get(key, [])
        )  # a toestand read again replaces its day
        points.update((day, crumbs) for crumbs, day in first.items())
        runs: list[tuple[str, Crumbs]] = []
        for day, crumbs in sorted(points.items(), key=lambda point: point[0]):
            if not runs or runs[-1][1] != crumbs:
                runs.append((day, crumbs))
        return {
            "breadcrumb": _serialised(runs[0][1]),
            "breadcrumb_changes": [
                {"from": day, "breadcrumb": _serialised(crumbs) or []}
                for day, crumbs in runs[1:]
            ]
            or None,
        }
