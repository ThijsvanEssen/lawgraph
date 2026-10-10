"""The coalition of a cabinet: who forms it on a day, and its seats in each Kamer over time
(``core.coalition``), from the posts of the cabinet and the seats of the members."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import CHAMBER_TK, RELATION_SERVED_IN, RELATION_VOTED
from lawgraph.core.coalition import (
    EK_SEATS,
    TK_SEATS_FROM,
    coalition_on,
    seat_timeline,
    tk_events,
)
from lawgraph.db import GraphStore
from lawgraph.db.counting import Store
from lawgraph.db.queries import ek_seats
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
    seat of the Tweede Kamer is known, ``TK_SEATS_FROM``), each with the events derived from
    the seats (``core.coalition.tk_events``); ``ek``, the stretches of the Eerste Kamer
    (``_ek_stretches``)."""
    props = cabinet.get("props") or {}
    start = str(props.get("from_date") or "")[:10]
    end = (
        _last_day(store, cabinet["_key"], str(props.get("to_date") or "")[:10]) or today
    )
    posts = cabinet_posts(store, cabinet["_key"])
    tk = None
    if start and start >= TK_SEATS_FROM:
        tk = seat_timeline(
            posts,
            memberships_between(store, start, end),
            start,
            end,
            vacancies_between(store, start, end),
        )
        abbreviations = faction_abbreviations(
            store, {f["key"] for segment in tk for f in segment["factions"]}
        )
        memberships = memberships_between(store, start, end)
        vacancies = vacancies_between(store, start, end)
        previous: set[str] | None = None
        for segment in tk:
            for faction in segment["factions"]:
                faction["abbreviation"] = abbreviations.get(faction["key"])
            now = {f["key"] for f in segment["factions"] if f["coalition"]}
            segment["events"] = tk_events(
                segment["from_date"], memberships, vacancies, previous, now
            )
            previous = now
    return {"tk": tk, "ek": _ek_stretches(store, posts, start, end)}


def _last_day(store: GraphStore, key: str, to_date: str) -> str:
    """The last day of the cabinet *key* that is its own: the day before *to_date* when its
    successor begins on it (Rutte IV ended on 2 July 2024, the day Schoof was sworn in:
    the seats of that day are the successor's), else *to_date*; empty while in office."""
    if not to_date:
        return ""
    on_it = cabinet_on(store, to_date)
    if on_it is None or on_it["key"] == key:
        return to_date
    return (dt.date.fromisoformat(to_date) - dt.timedelta(days=1)).isoformat()


def _ek_stretches(
    store: GraphStore, posts: list[dict[str, Any]], start: str, end: str
) -> list[dict[str, Any]] | None:
    """The stretches of the Eerste Kamer in *start*..*end* (``lg_ek_seats``), clipped to it,
    in the shape of the Tweede Kamer's: each faction with its seats and whether it is of the
    coalition (by name, as ``Coalition.has`` matches the Eerste Kamer), the changes that
    began the stretch (``events``, in the source's words) and whether its term added up
    (``checked``); None when none is known."""
    rows = ek_seats.stretches_between(store, start, end)
    if not rows:
        return None
    keys = {
        str((doc.get("props") or {}).get("abbreviation") or "").upper(): doc["_key"]
        for doc in get_factions(store, chamber="EK")
    }
    stretches = []
    for row in rows:
        first = max(row["from_date"], start)
        last = min(row["to_date"] or end, end)
        names = _names(store, posts, coalition_on(posts, first))
        ranked = sorted(
            (
                (name, n, name.upper() in names)
                for name, n in (row["seats"] or {}).items()
                if n > 0
            ),
            key=lambda r: (not r[2], -r[1], r[0]),
        )
        stretches.append(
            {
                "from_date": first,
                "to_date": last,
                "coalition": sum(n for _, n, c in ranked if c),
                "opposition": sum(n for _, n, c in ranked if not c),
                "vacant": max(EK_SEATS - sum(n for _, n, _c in ranked), 0),
                "factions": [
                    {
                        "key": keys.get(name.upper()),
                        "abbreviation": name,
                        "seats": n,
                        "coalition": c,
                    }
                    for name, n, c in ranked
                ],  # fmt: skip
                "events": [_ek_event(e) for e in row["events"] or []]
                if row["from_date"] >= start
                else [],
                "checked": bool(row["checked"]),
            }
        )
    return stretches


def _ek_event(change: dict[str, Any]) -> dict[str, Any]:
    """A change of ``core.ek_changes`` as an event of a stretch."""
    factions = [
        f
        for f in (change.get("source"), change.get("to"), *change.get("sources", []))
        if f
    ]
    return {
        "kind": change["kind"],
        "date": change["date"],
        "words": change.get("words"),
        "basis": change.get("basis"),
        "factions": factions,
        "members": [change["member"]] if change.get("member") else [],
    }


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


# ── what the coalition did on each vote (``semantic tk-coalition-votes``) ─────────


def cabinets_with_posts(store: Store) -> list[dict[str, Any]]:
    """``{key, from_date, to_date, posts}`` of every cabinet, newest first: the posts held in
    it (``meta.posts`` of its ``SERVED_IN`` edges)."""
    rows = store.query(
        """
        SELECT c.key, lg_str(c.props -> 'from_date') AS from_date,
               lg_str(c.props -> 'to_date') AS to_date,
               coalesce((
                   SELECT json_agg(p.post ORDER BY e.key, p.n)
                   FROM edges e
                   CROSS JOIN LATERAL json_array_elements(
                       CASE WHEN json_typeof(e.doc -> 'meta' -> 'posts') = 'array'
                            THEN e.doc -> 'meta' -> 'posts' ELSE '[]'::json END
                   ) WITH ORDINALITY AS p(post, n)
                   WHERE e.to_id = c.id AND e.relation = %(served_in)s
               ), '[]'::json) AS posts
        FROM cabinets c
        WHERE lg_str(c.props -> 'from_date') IS NOT NULL
        ORDER BY lg_str(c.props -> 'from_date') DESC NULLS LAST, c.key ASC
        """,
        {"served_in": RELATION_SERVED_IN},
    )
    return list(rows)


def decision_votes(store: Store, since_date: str | None) -> Any:
    """``{id, date, voter_collection, voter, choice, seats}`` of every vote on a decision of
    the Tweede Kamer (dated *since_date* or later when given), by decision: a faction with
    its seats that day (``meta.seats``), or a member of a roll call."""
    since = "AND d.date >= %(since)s" if since_date else ""
    return store.query(
        f"""
        SELECT d.id, d.date, e.from_collection AS voter_collection,
               split_part(e.from_id, '/', 2) AS voter,
               lg_str(e.doc -> 'meta' -> 'choice') AS choice,
               coalesce(lg_num(e.doc -> 'meta' -> 'seats'), 0)::int AS seats
        FROM decisions d
        JOIN edges e ON e.to_id = d.id AND e.relation = %(voted)s
        WHERE %(tk)s = ANY(d.labels) AND d.date IS NOT NULL {since}
        ORDER BY d.id ASC, e.key ASC
        """,
        {"voted": RELATION_VOTED, "tk": CHAMBER_TK, "since": since_date},
    )


_COLUMNS = (
    "id",
    "cabinet",
    "coalition_for",
    "coalition_against",
    "opposition_for",
    "opposition_against",
    "pattern",
    "carried",
    "decisive",
    "factions",
)


def coalition_object(row: str) -> str:
    """SQL: what the coalition did on a vote, from the row *row* of ``lg_decision_coalition``
    (null without one); what the list and the detail of decisions and the feed give."""
    return f"""CASE WHEN {row}.id IS NULL THEN NULL ELSE json_build_object(
        'cabinet', {row}.cabinet,
        'coalition_for', {row}.coalition_for,
        'coalition_against', {row}.coalition_against,
        'opposition_for', {row}.opposition_for,
        'opposition_against', {row}.opposition_against,
        'pattern', {row}.pattern,
        'carried', {row}.carried,
        'decisive', {row}.decisive
    ) END"""


def coalition_factions(row: str) -> str:
    """SQL: each coalition faction's choice on a vote, from the row *row* of
    ``lg_decision_coalition``, ``[{key, short, choice, seats_for, seats_against}]`` in the order kept
    (most seats first); ``[]`` without one. ``short`` is the faction's abbreviation, else
    its name."""
    return f"""(
        SELECT coalesce(json_agg(json_build_object(
            'key', x.f -> 'key',
            'short', (SELECT coalesce(lg_str(fa.props -> 'abbreviation'),
                                      lg_str(fa.props -> 'name'))
                      FROM factions fa WHERE fa.key = x.f ->> 'key'),
            'choice', x.f -> 'choice',
            'seats_for', x.f -> 'seats_for',
            'seats_against', x.f -> 'seats_against'
        ) ORDER BY x.n), '[]'::json)
        FROM json_array_elements(coalesce({row}.factions, '[]'::json))
            WITH ORDINALITY AS x(f, n)
    )"""


def keep_decision_coalition(store: Store, rows: list[dict[str, Any]]) -> None:
    """Write the rows of ``lg_decision_coalition``, replacing those of the same decision."""
    if not rows:
        return
    names = ", ".join(_COLUMNS)
    store.execute(
        f"""
        INSERT INTO lg_decision_coalition ({names})
        SELECT {names} FROM json_populate_recordset(
            NULL::lg_decision_coalition, %(rows)s::json
        )
        ON CONFLICT (id) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMNS[1:])}
        """,
        {"rows": json.dumps([{c: row[c] for c in _COLUMNS} for row in rows])},
    )


def remove_decision_coalition_except(store: Store, keep: list[str]) -> int:
    """Remove the rows of the decisions not in *keep* (a full run: no coalition vote any
    more); how many went."""
    return len(
        store.execute(
            """
            DELETE FROM lg_decision_coalition c
            WHERE NOT EXISTS (SELECT 1 FROM unnest(%(keep)s::text[]) k WHERE k = c.id)
            RETURNING 1
            """,
            {"keep": keep},
        )
    )


def vacancies_between(store: Store, start: str, end: str) -> list[dict[str, Any]]:
    """``{faction_key, from_date, to_date}`` of every vacant seat of a faction of the
    Tweede Kamer (``vacancies``, FractieZetelVacature) that overlaps *start*..*end*."""
    rows = store.query(
        """
        SELECT f.key AS faction_key, lg_str(v.period -> 'from_date') AS from_date,
               lg_str(v.period -> 'to_date') AS to_date
        FROM factions f
        CROSS JOIN LATERAL json_array_elements(
            CASE WHEN json_typeof(f.props -> 'vacancies') = 'array'
                 THEN f.props -> 'vacancies' ELSE '[]'::json END
        ) AS v(period)
        WHERE lg_str(v.period -> 'from_date') <= %(end)s
          AND (lg_str(v.period -> 'to_date') IS NULL
               OR lg_str(v.period -> 'to_date') >= %(start)s)
        ORDER BY 1 ASC NULLS FIRST, 2 ASC NULLS FIRST
        """,
        {"start": start, "end": end},
    )
    return list(rows)
