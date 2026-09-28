"""Queries behind the cabinet and commitment endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_MEMBERS,
    LABEL_RIJKSOVERHEID,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_MADE_IN,
    RELATION_PART_OF,
    RELATION_SERVED_IN,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, NO_DUE_DATE
from lawgraph.db import ArangoStore

# The track of a bill the government brings in.
TRACK_BILL = "wetsvoorstel"
COMMITMENT_OPEN = "open"


def _name(member: str) -> str:
    """AQL: the name *member* goes by; for a TK person without one, the name Rijksoverheid
    gives (``David van Weel``, else ``D.M. van Weel``)."""
    return f"{member}.props.name OR {member}.props.known_as OR {member}.props.government_name"


# The member of a SERVED_IN edge as a list and detail item name it.
_PERSON = f"{{ key: member._key, name: {_name('member')} }}"


def get_cabinets(store: ArangoStore) -> list[dict[str, Any]]:
    """Every cabinet, newest first, with its prime minister and counts: ``members`` (who
    held a post in it), ``bills`` (government bills brought in under it) and
    ``commitments`` (made under it)."""
    aql = f"""
    LET bill_counts = MERGE(
        FOR d IN {COLLECTION_DOSSIERS}
            FILTER d.props.cabinet != null AND d.props.initiative == false
            FILTER d.props.track_kind == @bill
            COLLECT cabinet = d.props.cabinet WITH COUNT INTO n
            RETURN {{ [cabinet]: n }}
    )
    LET commitment_counts = MERGE(
        FOR c IN {COLLECTION_COMMITMENTS}
            FILTER c.props.cabinet != null
            COLLECT cabinet = c.props.cabinet WITH COUNT INTO n
            RETURN {{ [cabinet]: n }}
    )
    FOR cabinet IN {COLLECTION_CABINETS}
        SORT cabinet.props.from_date DESC
        LET served = LENGTH(
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == cabinet._id AND e.relation == @served_in
                RETURN 1
        )
        LET member = cabinet.props.prime_minister != null
            ? DOCUMENT({COLLECTION_MEMBERS}, cabinet.props.prime_minister) : null
        RETURN {{
            cabinet: cabinet,
            prime_minister: member != null ? {_PERSON} : null,
            members: served,
            bills: bill_counts[cabinet._key] OR 0,
            commitments: commitment_counts[cabinet._key] OR 0
        }}
    """
    return list(store.query(aql, {"bill": TRACK_BILL, "served_in": RELATION_SERVED_IN}))


def get_cabinet(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """One cabinet with every member and their posts in it, and per member the counts
    ``dossiers`` (signed first or with others as a bewindspersoon within the cabinet's
    period, directly or through a case), ``bills`` (of those, government bills) and
    ``open_commitments`` (made under it and still open); None when unknown."""
    aql = f"""
    LET cabinet = DOCUMENT({COLLECTION_CABINETS}, @key)
    FILTER cabinet != null
    LET start = cabinet.props.from_date
    LET end = cabinet.props.to_date OR @today
    LET prime = cabinet.props.prime_minister != null
        ? DOCUMENT({COLLECTION_MEMBERS}, cabinet.props.prime_minister) : null
    LET bill_count = LENGTH(
        FOR d IN {COLLECTION_DOSSIERS}
            FILTER d.props.cabinet == cabinet._key AND d.props.initiative == false
            FILTER d.props.track_kind == @bill
            RETURN 1
    )
    LET commitment_count = LENGTH(
        FOR c IN {COLLECTION_COMMITMENTS}
            FILTER c.props.cabinet == cabinet._key
            RETURN 1
    )
    LET posts = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == cabinet._id AND e.relation == @served_in
            LET member = DOCUMENT(e._from)
            FILTER member != null
            LET signed = UNIQUE(
                FOR a IN {COLLECTION_EDGES}
                    FILTER a._from == member._id AND a.relation == @authored
                    FILTER a.meta.capacity == @government
                    LET date = DOCUMENT(a._to).props.date
                    FILTER date != null AND date >= start AND date <= end
                    FOR p IN {COLLECTION_EDGES}
                        FILTER p._from == a._to AND p.relation == @part_of
                        FOR target IN STARTS_WITH(p._to, "{COLLECTION_CASES}/")
                            ? (FOR q IN {COLLECTION_EDGES}
                                FILTER q._from == p._to AND q.relation == @part_of
                                FILTER STARTS_WITH(q._to, "{COLLECTION_DOSSIERS}/")
                                RETURN q._to)
                            : [p._to]
                            FILTER STARTS_WITH(target, "{COLLECTION_DOSSIERS}/")
                            RETURN target
            )
            RETURN {{
                member: {_PERSON},
                posts: e.meta.posts OR [],
                dossiers: LENGTH(signed),
                bills: LENGTH(
                    FOR id IN signed
                        FILTER DOCUMENT(id).props.track_kind == @bill
                        RETURN 1
                ),
                open_commitments: LENGTH(
                    FOR c IN {COLLECTION_COMMITMENTS}
                        FILTER c.props.member_key == member._key
                        FILTER c.props.cabinet == cabinet._key
                        FILTER c.props.status == @open
                        RETURN 1
                )
            }}
    )
    RETURN {{
        cabinet: cabinet,
        prime_minister: prime != null ? {{
            key: prime._key, name: {_name("prime")}
        }} : null,
        members: posts,
        bills: bill_count,
        commitments: commitment_count
    }}
    """
    bind = {
        "key": key,
        "today": dt.date.today().isoformat(),
        "served_in": RELATION_SERVED_IN,
        "authored": RELATION_AUTHORED,
        "government": CAPACITY_GOVERNMENT,
        "part_of": RELATION_PART_OF,
        "bill": TRACK_BILL,
        "open": COMMITMENT_OPEN,
    }
    rows = list(store.query(aql, bind))
    return cast(dict[str, Any], rows[0]) if rows else None


# What a commitment item shows beside its own props: who made it, its dossiers and the
# activity it was made in.
_COMMITMENT_ITEM = f"""{{
    commitment: c,
    member: c.props.member_key != null ? FIRST(
        FOR m IN {COLLECTION_MEMBERS}
            FILTER m._key == c.props.member_key
            RETURN {{ key: m._key, name: {_name("m")} }}
    ) : null,
    dossiers: (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == c._id AND e.relation == @about
            FILTER STARTS_WITH(e._to, "{COLLECTION_DOSSIERS}/")
            LET d = DOCUMENT(e._to)
            FILTER d != null
            SORT d.props.label
            RETURN {{ key: d._key, number: d.props.label, title: d.props.title }}
    ),
    activity: FIRST(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == c._id AND e.relation == @made_in
            FILTER STARTS_WITH(e._to, "{COLLECTION_ACTIVITIES}/")
            LET a = DOCUMENT(e._to)
            FILTER a != null
            RETURN {{ key: a._key, date: a.props.date, number: a.props.number }}
    )
}}"""


# The dimensions a commitment list counts as facets, and the prop each counts.
_COMMITMENT_FACETS = {
    "status": "c.props.status",
    "cabinet": "c.props.cabinet",
    "ministry": "c.props.ministry",
}


def get_commitments(
    store: ArangoStore,
    *,
    status: str | None = None,
    member: str | None = None,
    cabinet: str | None = None,
    ministry: str | None = None,
    dossier: str | None = None,
    due_before: str | None = None,
    overdue: bool = False,
    q: str | None = None,
    sort: str = "date",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of commitments, the total and ``facets``: per ``status``, ``cabinet`` and
    ``ministry`` the number of commitments per value under the other filters, each
    dimension counted without its own filter. *dossier* is a number (``36600``) or the
    label of a dossier (``36600-VII``); *overdue* keeps the open ones whose expected date
    has passed; *sort* is ``date`` (newest made first) or ``expected_resolution`` (soonest
    first, those without one last)."""
    shared: list[str] = []
    own: dict[str, str] = {}
    bind: dict[str, Any] = {
        "limit": limit,
        "offset": offset,
        "about": RELATION_ABOUT,
        "made_in": RELATION_MADE_IN,
    }
    for name, value in (
        ("status", status),
        ("cabinet", cabinet),
        ("ministry", ministry),
    ):
        if value:
            own[name] = f"{_COMMITMENT_FACETS[name]} == @{name}"
            bind[name] = value
    if member:
        shared.append("c.props.member_key == @member")
        bind["member"] = member
    if due_before:
        shared.append(
            "c.props.expected_resolution != @no_date"
            " AND c.props.expected_resolution < @due_before"
        )
        bind["due_before"] = due_before
        bind["no_date"] = NO_DUE_DATE
    if overdue:
        shared.append(
            "c.props.status == @open AND c.props.expected_resolution != @no_date"
            " AND c.props.expected_resolution < @today"
        )
        bind["open"] = COMMITMENT_OPEN
        bind["no_date"] = NO_DUE_DATE
        bind["today"] = dt.date.today().isoformat()
    if q:
        shared.append("CONTAINS(LOWER(c.props.text), @q)")
        bind["q"] = q.strip().lower()
    if dossier:
        shared.append(
            f"""LENGTH(
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == c._id AND e.relation == @about
                    LET d = DOCUMENT(e._to)
                    FILTER d.props.label == @dossier OR d.props.number == @dossier
                    LIMIT 1 RETURN 1
            ) > 0"""
        )
        bind["dossier"] = dossier
    if sort == "expected_resolution":
        bind["no_date"] = NO_DUE_DATE
        order = (
            "(c.props.expected_resolution == null"
            " OR c.props.expected_resolution == @no_date) ASC,"
            " c.props.expected_resolution ASC, c.props.made_on DESC"
        )
    else:
        order = "c.props.made_on DESC"

    def where(*clauses: str) -> str:
        return "\n            ".join(f"FILTER {c}" for c in clauses)

    facets = ",\n        ".join(
        f"""{name}: (
            FOR c IN {COLLECTION_COMMITMENTS}
                {where(*shared, *(c for n, c in own.items() if n != name))}
                COLLECT value = {expression} WITH COUNT INTO n
                SORT n DESC, value
                RETURN {{ value, count: n }}
        )"""
        for name, expression in _COMMITMENT_FACETS.items()
    )
    aql = f"""
    LET matching = (
        FOR c IN {COLLECTION_COMMITMENTS}
            {where(*shared, *own.values())}
            RETURN c
    )
    RETURN {{
        total: LENGTH(matching),
        items: (
            FOR c IN matching
                SORT {order}, c._key
                LIMIT @offset, @limit
                RETURN {_COMMITMENT_ITEM}
        ),
        facets: {{
        {facets}
        }}
    }}
    """
    rows = list(store.query(aql, bind))
    return (
        cast(dict[str, Any], rows[0])
        if rows
        else {"total": 0, "items": [], "facets": {}}
    )


def get_commitment(store: ArangoStore, key: str) -> dict[str, Any] | None:
    """One commitment as a list item; None when unknown."""
    aql = f"""
    FOR c IN {COLLECTION_COMMITMENTS}
        FILTER c._key == @key
        RETURN {_COMMITMENT_ITEM}
    """
    rows = list(
        store.query(
            aql, {"key": key, "about": RELATION_ABOUT, "made_in": RELATION_MADE_IN}
        )
    )
    return cast(dict[str, Any], rows[0]) if rows else None


def cabinets_with_posts(store: ArangoStore) -> list[dict[str, Any]]:
    """Every cabinet, oldest first, with every post held in it (``lawgraph verify
    cabinets``): ``{key, props, posts}``, each post with ``member`` (its key) and ``own``
    (a member only Rijksoverheid knows)."""
    aql = f"""
    FOR cabinet IN {COLLECTION_CABINETS}
        SORT cabinet.props.from_date, cabinet._key
        RETURN {{
            key: cabinet._key,
            props: cabinet.props,
            posts: (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == cabinet._id AND e.relation == @served_in
                    LET member = DOCUMENT(e._from)
                    FOR post IN e.meta.posts OR []
                        RETURN MERGE(post, {{
                            member: PARSE_IDENTIFIER(e._from).key,
                            own: @own IN (member.labels OR [])
                        }})
            )
        }}
    """
    return list(
        store.query(aql, {"served_in": RELATION_SERVED_IN, "own": LABEL_RIJKSOVERHEID})
    )
