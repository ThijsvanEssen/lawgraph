"""Queries behind an office: who held a seat, and what is attributed to it.

What belongs to a seat is worked out when asked (``core.seats``), from what the pipelines
stored: the posts on a member (``government_functions``), and who made a commitment or signed
a dossier first. No derived table, so nothing to backfill; a list keeps the ids found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.core.cabinet_posts import seat_gaps
from lawgraph.core.seats import (
    base_seat,
    family,
    is_of_kind,
    merged_from,
    merged_into,
    ministries_of,
    seat_acted_from,
)
from lawgraph.core.signatories import held_on
from lawgraph.core.tk_records.actors import CAPACITY_GOVERNMENT
from lawgraph.db import GraphStore
from lawgraph.db.queries._json_sql import has_length
from lawgraph.db.queries.cabinets import person_object


@dataclass(frozen=True)
class Attribution:
    """What is attributed to a seat: the ids, and how many others may be its own but fit
    nobody (of its ministry and kind, on a day it was held, with no member found or a member
    who fits no one seat that day)."""

    ids: list[str]
    unattributed: int


def _people(store: GraphStore) -> list[dict[str, Any]]:
    """Everyone who held a post: ``{member: {key, name, slug}, posts}``."""
    posts = "m.props -> 'government_functions'"
    return list(
        store.query(
            f"""
            SELECT json_build_object('member', {person_object("m")}, 'posts', {posts})
            FROM members m
            WHERE {has_length(posts)}
            ORDER BY m.key
            """
        )
    )


def _held(people: list[dict[str, Any]], seat: str) -> list[dict[str, Any]]:
    """The posts of *seat* over its renames, each with its ``member``, oldest first."""
    names = set(family(seat))
    held = [
        {**post, "member": person["member"]}
        for person in people
        for post in person["posts"]
        if base_seat(post.get("seat") or "") in names
    ]
    return sorted(held, key=lambda post: post.get("from_date") or "")


def _attribute(
    store: GraphStore, seat: str, statement: str, people: list[dict[str, Any]]
) -> Attribution:
    """The rows of *statement* (``{id, member, day, function, ministry}``), bound to the
    holders of *seat* and its ministries, as attributed to it."""
    held = _held(people, seat)
    posts = {person["member"]["key"]: person["posts"] for person in people}
    own = family(seat)[0]
    ministries = ministries_of(seat)
    ids: list[str] = []
    unattributed = 0
    rows = store.query(
        statement,
        {
            "holders": sorted({post["member"]["key"] for post in held}),
            "ministries": ministries,
            "government": CAPACITY_GOVERNMENT,
        },
    )
    for row in rows:
        day, function = row["day"], row["function"]
        acted = seat_acted_from(
            posts.get(row["member"]) or [],
            day=day,
            function=function,
            ministry=row["ministry"],
        )
        if acted == own:
            ids.append(row["id"])
        elif (
            acted is None
            and day
            and row["ministry"] in ministries
            and is_of_kind(seat, function)
            and any(held_on(post, day) for post in held)
        ):
            unattributed += 1
    return Attribution(ids, unattributed)


_COMMITMENTS = """
    SELECT json_build_object(
        'id', c.id, 'member', c.member_key, 'day', c.made_on,
        'function', c.props -> 'minister_role', 'ministry', c.ministry
    )
    FROM commitments c
    WHERE c.member_key = ANY(%(holders)s) OR c.ministry = ANY(%(ministries)s)
"""

_DOSSIERS = """
    SELECT json_build_object(
        'id', d.id, 'member', d.first ->> 'member', 'day', d.first ->> 'date',
        'function', d.first ->> 'function', 'ministry', d.ministry
    )
    FROM (
        SELECT ds.id, ds.ministry, ds.props -> 'first_signed' AS first FROM dossiers ds
        WHERE lg_str(ds.props -> 'first_signed' -> 'capacity') = %(government)s
        OFFSET 0
    ) d
    WHERE d.first ->> 'member' = ANY(%(holders)s) OR d.ministry = ANY(%(ministries)s)
"""


def seat_commitments(
    store: GraphStore, seat: str, people: list[dict[str, Any]] | None = None
) -> Attribution:
    """The commitments of *seat*: made by the member who acted from it that day."""
    return _attribute(store, seat, _COMMITMENTS, people or _people(store))


def seat_dossiers(
    store: GraphStore, seat: str, people: list[dict[str, Any]] | None = None
) -> Attribution:
    """The dossiers of *seat*: brought in by the bewindspersoon who acted from it the day
    they signed its earliest signed document first."""
    return _attribute(store, seat, _DOSSIERS, people or _people(store))


def _existing(seats: list[str], people: list[dict[str, Any]]) -> list[str]:
    """Of *seats*, those someone held."""
    known = {
        base_seat(post.get("seat") or "")
        for person in people
        for post in person["posts"]
    }
    return [seat for seat in seats if seat in known]


def get_seat(store: GraphStore, seat: str) -> dict[str, Any] | None:
    """An office over its renames: ``seat`` by its latest name, ``names`` oldest first,
    ``holders``, ``gaps`` (longer than ``GAP_DAYS`` without a holder), the seats of a merger
    and what is attributed to it; None when nobody held it."""
    people = _people(store)
    held = _held(people, seat)
    if not held:
        return None
    names = list(dict.fromkeys(base_seat(post["seat"]) for post in held))
    dated = [post for post in held if post.get("from_date")]
    return {
        "seat": names[-1],
        "names": names,
        "merged_from": _existing(merged_from(seat), people),
        "merged_into": _existing(merged_into(seat), people),
        "holders": held,
        "gaps": [
            {"from_date": gap["from_date"], "to_date": gap["to_date"]}
            for gap in seat_gaps([{**post, "seat": names[-1]} for post in dated])
        ],
        "commitments": seat_commitments(store, seat, people),
        "dossiers": seat_dossiers(store, seat, people),
    }
