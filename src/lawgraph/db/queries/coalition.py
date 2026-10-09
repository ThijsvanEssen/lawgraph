"""The coalition of a cabinet: who forms it on a day, and its seats in each Kamer over time
(``core.coalition``), from the posts of the cabinet and the seats of the members."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.coalition import TK_SEATS_FROM, coalition_on, seat_timeline
from lawgraph.db import GraphStore
from lawgraph.db.queries.cabinets import (
    cabinet_on,
    cabinet_posts,
    memberships_between,
)
from lawgraph.db.queries.committees import get_factions


@dataclass(frozen=True)
class Coalition:
    """The coalition on a day: its cabinet (``key``, ``name``), its factions in the Tweede
    Kamer (keys), and the names its parties go by (upper case: the short name of each
    post's party, the abbreviation of each of its factions), by which a faction of the
    Eerste Kamer is matched."""

    cabinet: dict[str, Any] | None
    factions: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)

    def has(self, key: str, abbreviation: str | None) -> bool:
        """Whether the faction *key* (of either Kamer) is of the coalition."""
        return key in self.factions or (abbreviation or "").upper() in self.names


def coalition_of_day(store: GraphStore, day: str) -> Coalition:
    """The coalition on *day*; no cabinet (and no factions) before 1945 or between two."""
    cabinet = cabinet_on(store, day)
    if cabinet is None:
        return Coalition(cabinet=None)
    posts = cabinet_posts(store, cabinet["key"])
    factions = coalition_on(posts, day)
    return Coalition(
        cabinet={"key": cabinet["key"], "name": cabinet.get("name")},
        factions=factions,
        names=_names(store, posts, factions),
    )


def cabinet_seats(
    store: GraphStore, cabinet: dict[str, Any], today: str
) -> dict[str, Any]:
    """The seats of the cabinet's coalition in each Kamer over its period: ``tk``, the
    timeline of ``core.coalition.seat_timeline`` (None for a cabinet that began before every
    seat of the Tweede Kamer is known, ``TK_SEATS_FROM``); ``ek``, one segment on the day
    the composition of the Eerste Kamer was read when the cabinet was in office then (None
    otherwise: the Eerste Kamer has no seats per day)."""
    props = cabinet.get("props") or {}
    start = str(props.get("from_date") or "")[:10]
    end = str(props.get("to_date") or "")[:10] or today
    posts = cabinet_posts(store, cabinet["_key"])
    tk = None
    if start and start >= TK_SEATS_FROM:
        tk = seat_timeline(posts, memberships_between(store, start, end), start, end)
        abbreviations = faction_abbreviations(
            store, {f["key"] for segment in tk for f in segment["factions"]}
        )
        for segment in tk:
            for faction in segment["factions"]:
                faction["abbreviation"] = abbreviations.get(faction["key"])
    return {"tk": tk, "ek": _ek_segment(store, posts, start, end)}


def _ek_segment(
    store: GraphStore, posts: list[dict[str, Any]], start: str, end: str
) -> list[dict[str, Any]] | None:
    factions = [
        doc
        for doc in get_factions(store, active=True, chamber="EK")
        if int((doc.get("props") or {}).get("seats") or 0) > 0
    ]
    read_on = max(
        (str((d.get("props") or {}).get("retrieved_on") or "") for d in factions),
        default="",
    )[:10]
    if not read_on or not (start <= read_on <= end):
        return None
    names = _names(store, posts, coalition_on(posts, read_on))
    rows = sorted(
        (
            (
                doc["_key"],
                (doc.get("props") or {}).get("abbreviation"),
                int(doc["props"]["seats"]),
                str((doc.get("props") or {}).get("abbreviation") or "").upper()
                in names,
            )
            for doc in factions
        ),
        key=lambda r: (not r[3], -r[2], r[0]),
    )
    return [
        {
            "from_date": read_on,
            "to_date": read_on,
            "coalition": sum(r[2] for r in rows if r[3]),
            "opposition": sum(r[2] for r in rows if not r[3]),
            "factions": [
                {"key": k, "abbreviation": a, "seats": n, "coalition": c}
                for k, a, n, c in rows
            ],
        }
    ]


def _names(
    store: GraphStore, posts: list[dict[str, Any]], factions: set[str]
) -> set[str]:
    """The names the parties of *factions* go by, upper case: the short name of each post's
    party and the abbreviation of each faction; what a faction of the Eerste Kamer is
    matched by."""
    names = {
        str((post.get("party") or {}).get("short") or "").upper()
        for post in posts
        if (post.get("party") or {}).get("faction") in factions
    }
    names |= {str(a).upper() for a in faction_abbreviations(store, factions).values()}
    names.discard("")
    return names


def faction_abbreviations(store: GraphStore, keys: set[str]) -> dict[str, str]:
    """Faction key -> its abbreviation, of the factions *keys* that have one."""
    if not keys:
        return {}
    rows = store.query(
        """
        SELECT f.key, lg_str(f.props -> 'abbreviation') AS abbreviation
        FROM factions f
        WHERE f.key = ANY(%(keys)s::text[]) AND lg_truthy(f.props -> 'abbreviation')
        """,
        {"keys": sorted(keys)},
    )
    return {row["key"]: row["abbreviation"] for row in rows}
