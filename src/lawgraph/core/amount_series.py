"""The numbers of an article over its versions: which version holds on a day, and the series
of each of its numbers through the versions before and after it.

A number of one version is the same number in another when it is the n-th of its kind and
source in the same part of both (``lid-2``: the first amount, the second amount). When the
part holds more or fewer of that kind in a version, the series stops there: no guess which
number is which."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# What makes numbers of two versions the same number, but for their place among them.
type _Key = tuple[str | None, str, str]


@dataclass
class Version:
    """A version of an article with its numbers (rows of ``amounts.article_amounts``)."""

    key: str
    valid_from: str | None
    valid_until: str | None
    current: bool
    rows: list[Mapping[str, Any]] = field(default_factory=list)

    def holds_on(self, day: str) -> bool:
        """Whether the version is in force on *day* (``yyyy-mm-dd``)."""
        return (self.valid_from or "") <= day and (
            self.valid_until is None or day < self.valid_until
        )


def versions(rows: Sequence[Mapping[str, Any]]) -> list[Version]:
    """The versions of the rows (oldest first, as read), each with its numbers."""
    found: dict[str, Version] = {}
    for row in rows:
        key = row["version_key"]
        if key not in found:
            found[key] = Version(
                key, row["version_from"], row["version_until"], bool(row["current"])
            )
        if row["kind"] is not None:
            found[key].rows.append(row)
    return list(found.values())


def version_on(found: Sequence[Version], day: str | None) -> int | None:
    """The place of the version in force on *day*; without a day the current one, else the
    newest. None when no version holds."""
    if day is not None:
        return next((i for i, v in enumerate(found) if v.holds_on(day)), None)
    current = [i for i, v in enumerate(found) if v.current]
    return current[-1] if current else (len(found) - 1 if found else None)


def _groups(version: Version) -> dict[_Key, list[Mapping[str, Any]]]:
    groups: dict[_Key, list[Mapping[str, Any]]] = defaultdict(list)
    for row in version.rows:
        groups[(row["part"], row["kind"], row["source"])].append(row)
    return groups


def _reach(groups: list[dict[_Key, list[Any]]], at: int, key: _Key) -> range:
    """The versions around *at* whose part holds as many numbers of *key* as *at*'s."""
    size = len(groups[at][key])
    first = at
    while first > 0 and len(groups[first - 1].get(key, ())) == size:
        first -= 1
    last = at
    while last + 1 < len(groups) and len(groups[last + 1].get(key, ())) == size:
        last += 1
    return range(first, last + 1)


def step(version: Version, row: Mapping[str, Any]) -> dict[str, Any]:
    """A number in one version: its value and from when to when it holds (the day of its
    redaction, else its version's start)."""
    return {
        "version_key": version.key,
        "valid_from": row["valid_from"] or version.valid_from,
        "valid_until": version.valid_until,
        "value": row["value"],
        "date": row["date"],
    }


def series(
    found: Sequence[Version], at: int
) -> list[tuple[Mapping[str, Any], list[dict[str, Any]]]]:
    """Each number of the version at *at*, by its place, with its series: a step per
    version it stands in, oldest first."""
    groups = [_groups(v) for v in found]
    out = []
    for key, rows in groups[at].items():
        reach = _reach(groups, at, key)
        for n, row in enumerate(rows):
            out.append((row, [step(found[i], groups[i][key][n]) for i in reach]))
    return sorted(out, key=lambda pair: pair[0]["span_start"])
