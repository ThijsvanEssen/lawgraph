"""What the server HTML of a readable address shows (``api/seo``): the node it names and
the sources it links to, each from light reads (columns, ``lg_judgment_light``,
``lg_document_light``, the covering indexes of the edges). The text of a judgment or a
paper is never read; that of an article is (it is the page).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_COMMITTEES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
    RELATION_AUTHORED,
    RELATION_MEMBER_OF,
    RELATION_REFERS_TO,
    RELATION_SERVED_IN,
)
from lawgraph.core.readable_paths import Pad, focus_of_pad
from lawgraph.db import GraphStore
from lawgraph.db.queries import lookup
from lawgraph.db.queries.decisions import get_document_decisions
from lawgraph.db.store import (
    ReadTimedOut,
    RequestCancelled,
    read_time_left,
    reset_read_deadline,
    set_read_deadline,
)
from lawgraph.db.version_cache import cached

T = TypeVar("T")

# How many sources a page links to of each kind: enough for a reader and a crawler, few
# enough for a page of a few tens of KB.
LINKS = 20
# The papers of a dossier a page lists, newest first.
PAPERS = 200
# The articles of a law its table of contents lists, in their order.
ARTICLES = 5000
# The members a page of a faction or committee lists, and the bewindspersonen of a cabinet.
MEMBERS = 300
# The seconds a page waits for the judgments citing an article (or the papers of a member)
# when they are not kept yet:
# of a much cited article (6:162 BW) they are thousands, and the page is its text first,
# as fast as the static shell (most visits come to an article no one asked for before).
# They are computed on in the background and kept per version of the tables they read,
# so a later page has them at once; the app fills them in for the first.
CITED_BUDGET = 0.05


def node_of(store: GraphStore, pad: Pad) -> str | None:
    """The node a readable address names, or None when the graph does not have it."""
    s = pad.soort
    if s == "uitspraak":
        return lookup.find_judgment(store, pad.a)
    if s == "wet":
        return lookup.find_law(store, pad.a)
    if s == "artikel":
        return lookup.find_article(store, pad.a, pad.b)
    if s == "dossier":
        return lookup.find_dossier(store, pad.a)
    if s == "kamerstuk":
        return lookup.find_document(store, pad.a, pad.b)
    if s == "publicatie":
        return lookup.find_publication(store, pad.a, pad.b, pad.c)
    if s == "lid":
        return lookup.find_member(store, pad.a)
    if s == "kabinet":
        return lookup.find_cabinet(store, pad.a)
    if s == "fractie":
        return lookup.find_faction(store, pad.a)
    if s == "commissie":
        return lookup.find_committee(store, pad.a)
    if s == "stemming":
        return f"decisions/{pad.a}" if store.has_node("decisions", pad.a) else None
    if s == "toezegging":
        return lookup.find_commitment(store, pad.a)
    return focus_of_pad(pad)


def _first(store: GraphStore, statement: str, params: dict[str, Any]) -> Any:
    return next(iter(store.query(statement, params)), None)


def law(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A law: its props, and its articles in their order (key, number), without their
    text; the repealed ones left out."""
    row = _first(
        store,
        f"SELECT id, key, props FROM {COLLECTION_INSTRUMENTS} WHERE id = %(id)s",
        {"id": node_id},
    )
    if row is None:
        return None
    articles = list(
        store.query(
            f"""
            SELECT a.key, a.article_number
            FROM {COLLECTION_ARTICLES} a
            WHERE a.bwb_id = %(bwb)s AND a.repealed IS NOT TRUE
              AND a.stub IS NOT TRUE AND a.article_number IS NOT NULL
            ORDER BY a.position ASC NULLS LAST, a.key ASC
            LIMIT %(limit)s
            """,
            {"bwb": (row["props"] or {}).get("bwb_id"), "limit": ARTICLES},
        )
    )
    return {**row, "articles": articles}


def article(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """An article (its props, its text too), its law and the judgments that cite it (the
    most cited first); without those (``judgments`` empty) while they are not kept yet and
    take past ``CITED_BUDGET`` (``cited``)."""
    row = _first(
        store,
        f"""
        SELECT a.id, a.key, a.props,
               (SELECT i.props FROM {COLLECTION_INSTRUMENTS} i
                WHERE i.bwb_id = a.bwb_id ORDER BY i.key LIMIT 1) AS law
        FROM {COLLECTION_ARTICLES} a
        WHERE a.id = %(id)s
        """,
        {"id": node_id},
    )
    if row is None:
        return None
    ids: list[str] = _within_budget(lambda: cited(store, node_id), [])
    return {**row, "judgments": _light(store, ids)}


def _within_budget(read: Callable[[], T], instead: T) -> T:
    """What *read* gives within ``CITED_BUDGET``, else *instead*: what is not kept yet goes
    on computing in the background for the next page."""
    left = read_time_left()
    token = set_read_deadline(CITED_BUDGET if left is None else min(CITED_BUDGET, left))
    try:
        return read()
    except RequestCancelled:
        raise
    except ReadTimedOut:
        return instead
    finally:
        reset_read_deadline(token)


def cited(store: GraphStore, node_id: str) -> list[str]:
    """The ``LINKS`` judgments that cite an article, the most cited first. Kept per
    version of the edges and the judgments: sorting the thousands that cite 6:162 BW takes
    about half a second, reading what is kept nothing."""
    return cached(
        store,
        ("seo article cited", node_id),
        lambda: _cited(store, node_id),
        tables=(COLLECTION_EDGES, COLLECTION_JUDGMENTS),
    )


def _light(store: GraphStore, ids: list[str]) -> list[dict[str, Any]]:
    """``{id, light}`` of the judgments *ids*, in their order."""
    if not ids:
        return []
    light = {
        row["id"]: row["light"]
        for row in store.query(
            "SELECT id, props AS light FROM lg_judgment_light"
            " WHERE id = ANY(%(ids)s::text[])",
            {"ids": ids},
        )
    }
    return [{"id": id_, "light": light.get(id_)} for id_ in ids]


def _cited(store: GraphStore, node_id: str) -> list[str]:
    return list(
        store.query(
            f"""
            SELECT j.id
            FROM edges e
            JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
            WHERE e.to_id = %(id)s AND e.relation = %(refers)s
              AND e.from_collection = '{COLLECTION_JUDGMENTS}'
            ORDER BY j.inbound_citation_count DESC NULLS LAST, j.key DESC
            LIMIT %(limit)s
            """,
            {"id": node_id, "refers": RELATION_REFERS_TO, "limit": LINKS},
        )
    )


def judgment(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A judgment: its light props and its whole summary (not its text), and the articles
    and judgments it cites."""
    row = _first(
        store,
        f"""
        SELECT j.id, j.key, l.props AS light, j.pj_summary AS summary
        FROM {COLLECTION_JUDGMENTS} j
        LEFT JOIN lg_judgment_light l ON l.id = j.id
        WHERE j.id = %(id)s
        """,
        {"id": node_id},
    )
    if row is None:
        return None
    articles = list(
        store.query(
            f"""
            SELECT a.id, a.bwb_id, a.celex, a.article_number,
                   (SELECT coalesce(lg_str(i.props -> 'short_title'),
                                    lg_str(i.props -> 'citation_title'))
                    FROM {COLLECTION_INSTRUMENTS} i
                    WHERE i.bwb_id = a.bwb_id ORDER BY i.key LIMIT 1) AS law
            FROM edges e
            JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
            WHERE e.from_id = %(id)s AND e.relation = %(refers)s
              AND e.to_collection = '{COLLECTION_ARTICLES}'
            ORDER BY a.bwb_id ASC NULLS LAST, a.position ASC NULLS LAST, a.key ASC
            LIMIT %(limit)s
            """,
            {"id": node_id, "refers": RELATION_REFERS_TO, "limit": LINKS},
        )
    )
    cited = list(
        store.query(
            f"""
            SELECT j.id, l.props AS light
            FROM edges e
            JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.to_id
            LEFT JOIN lg_judgment_light l ON l.id = j.id
            WHERE e.from_id = %(id)s AND e.relation = %(refers)s
              AND e.to_collection = '{COLLECTION_JUDGMENTS}'
            ORDER BY j.date_eff DESC NULLS LAST, j.key ASC
            LIMIT %(limit)s
            """,
            {"id": node_id, "refers": RELATION_REFERS_TO, "limit": LINKS},
        )
    )
    return {**row, "articles": articles, "judgments": cited}


def paper(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A paper of a chamber: its light props (``dictum`` when it has one), its subject,
    kind, date, chamber and signatures (columns), and the votes taken on it."""
    row = _first(
        store,
        f"""
        SELECT d.id, d.key, d.labels, d.kind, d.date, l.props AS light,
               d.pj_subject AS subject, d.pj_actors AS actors
        FROM {COLLECTION_DOCUMENTS} d
        LEFT JOIN lg_document_light l ON l.id = d.id
        WHERE d.id = %(id)s
        """,
        {"id": node_id},
    )
    if row is None:
        return None
    return {**row, "decisions": get_document_decisions(store, node_id)}


def dossier(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A dossier: its props, and its papers, newest first, light, with their total."""
    row = _first(
        store,
        f"SELECT id, key, props FROM {COLLECTION_DOSSIERS} WHERE id = %(id)s",
        {"id": node_id},
    )
    if row is None:
        return None
    label = (row["props"] or {}).get("label") or row["key"]
    papers = list(
        store.query(
            f"""
            SELECT d.id, d.kind, d.date, l.props AS light, d.pj_subject AS subject
            FROM {COLLECTION_DOCUMENTS} d
            LEFT JOIN lg_document_light l ON l.id = d.id
            WHERE d.dossier_numbers @> ARRAY[%(label)s]::text[]
            ORDER BY d.date DESC NULLS LAST, d.key ASC
            LIMIT %(limit)s
            """,
            {"label": label, "limit": PAPERS},
        )
    )
    total = _first(
        store,
        f"SELECT count(*)::int FROM {COLLECTION_DOCUMENTS} d"
        " WHERE d.dossier_numbers @> ARRAY[%(label)s]::text[]",
        {"label": label},
    )
    return {**row, "papers": papers, "total": total}


# ── people and bodies of the chambers and the government ──────────────────────

# A membership not ended: a seat of the Tweede Kamer without its last day, one of the
# Eerste Kamer still on its page.
_CURRENT = (
    "lg_str(e.doc -> 'meta' -> 'to_date') IS NULL"
    " AND lg_str(e.doc -> 'meta' -> 'observed_until') IS NULL"
)


def _node(store: GraphStore, table: str, node_id: str) -> dict[str, Any] | None:
    return _first(
        store,
        f"SELECT id, key, props FROM {table} WHERE id = %(id)s",
        {"id": node_id},
    )


def member(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A member: their props, and the papers they signed, newest first (without them while
    they are not kept yet and take past ``CITED_BUDGET``)."""
    row = _node(store, COLLECTION_MEMBERS, node_id)
    if row is None:
        return None
    ids: list[str] = _within_budget(lambda: authored(store, node_id), [])
    papers = list(
        store.query(
            f"""
            SELECT d.id, d.kind, d.date, l.props AS light, d.pj_subject AS subject
            FROM {COLLECTION_DOCUMENTS} d
            LEFT JOIN lg_document_light l ON l.id = d.id
            WHERE d.id = ANY(%(ids)s::text[])
            ORDER BY d.date DESC NULLS LAST, d.key ASC
            """,
            {"ids": ids},
        )
    )
    return {**row, "papers": papers}


def authored(store: GraphStore, node_id: str) -> list[str]:
    """The ``LINKS`` papers a member signed, newest first. Kept per version of the edges
    and the papers: of a member long in the Kamer they are thousands to sort."""
    return cached(
        store,
        ("seo member papers", node_id),
        lambda: _authored(store, node_id),
        tables=(COLLECTION_EDGES, COLLECTION_DOCUMENTS),
    )


def _authored(store: GraphStore, node_id: str) -> list[str]:
    return list(
        store.query(
            f"""
            SELECT d.id
            FROM edges e
            JOIN {COLLECTION_DOCUMENTS} d ON d.id = e.to_id
            WHERE e.from_id = %(id)s AND e.relation = %(authored)s
              AND e.to_collection = '{COLLECTION_DOCUMENTS}'
            ORDER BY d.date DESC NULLS LAST, d.key DESC
            LIMIT %(limit)s
            """,
            {"id": node_id, "authored": RELATION_AUTHORED, "limit": LINKS},
        )
    )


def _members_of(store: GraphStore, node_id: str) -> list[dict[str, Any]]:
    """The members of a faction or committee now, by name: ``id``, ``name``, ``slug`` and
    the ``meta`` of their membership (its role)."""
    return list(
        store.query(
            f"""
            SELECT m.id, coalesce(lg_str(m.props -> 'name'),
                                  lg_str(m.props -> 'display_name')) AS name,
                   lg_str(m.props -> 'slug') AS slug, e.doc -> 'meta' AS meta
            FROM edges e
            JOIN {COLLECTION_MEMBERS} m ON m.id = e.from_id
            WHERE e.to_id = %(id)s AND e.relation = %(member_of)s
              AND e.from_collection = '{COLLECTION_MEMBERS}' AND {_CURRENT}
            ORDER BY lg_str(m.props -> 'family_name') ASC NULLS LAST, name ASC NULLS LAST, m.id
            LIMIT %(limit)s
            """,
            {"id": node_id, "member_of": RELATION_MEMBER_OF, "limit": MEMBERS},
        )
    )


def faction(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A faction: its props and its members now."""
    row = _node(store, COLLECTION_FACTIONS, node_id)
    if row is None:
        return None
    return {**row, "members": _members_of(store, node_id)}


def committee(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A committee: its props and its members now, with their role."""
    row = _node(store, COLLECTION_COMMITTEES, node_id)
    if row is None:
        return None
    return {**row, "members": _members_of(store, node_id)}


def cabinet(store: GraphStore, node_id: str) -> dict[str, Any] | None:
    """A cabinet: its props, its bewindspersonen with their posts (``SERVED_IN``), the name
    and slug of its prime minister, the name of the cabinet before it and the names of
    its factions."""
    row = _node(store, COLLECTION_CABINETS, node_id)
    if row is None:
        return None
    props = row["props"] or {}
    served = list(
        store.query(
            f"""
            SELECT m.id, coalesce(lg_str(m.props -> 'name'),
                                  lg_str(m.props -> 'display_name')) AS name,
                   lg_str(m.props -> 'slug') AS slug,
                   e.doc -> 'meta' -> 'posts' AS posts
            FROM edges e
            JOIN {COLLECTION_MEMBERS} m ON m.id = e.from_id
            WHERE e.to_id = %(id)s AND e.relation = %(served_in)s
              AND e.from_collection = '{COLLECTION_MEMBERS}'
            ORDER BY name ASC NULLS LAST, m.id
            LIMIT %(limit)s
            """,
            {"id": node_id, "served_in": RELATION_SERVED_IN, "limit": MEMBERS},
        )
    )
    keys = [k for k in props.get("factions") or [] if isinstance(k, str)]
    factions = {
        r["key"]: r["name"]
        for r in store.query(
            f"""
            SELECT key, coalesce(lg_str(props -> 'abbreviation'),
                                 lg_str(props -> 'name')) AS name
            FROM {COLLECTION_FACTIONS} WHERE key = ANY(%(keys)s::text[])
            """,
            {"keys": keys},
        )
    }
    pm = props.get("prime_minister")
    prime_minister = (
        _first(
            store,
            f"""
            SELECT id, coalesce(lg_str(props -> 'name'),
                                lg_str(props -> 'display_name')) AS name,
                   lg_str(props -> 'slug') AS slug
            FROM {COLLECTION_MEMBERS} WHERE key = %(key)s
            """,
            {"key": pm},
        )
        if isinstance(pm, str)
        else None
    )
    before = props.get("previous")
    previous = (
        _first(
            store,
            f"SELECT lg_str(props -> 'name') FROM {COLLECTION_CABINETS}"
            " WHERE key = %(key)s",
            {"key": before},
        )
        if isinstance(before, str)
        else None
    )
    return {
        **row,
        "served": served,
        "factions": [(k, factions[k]) for k in keys if k in factions],
        "prime_minister": prime_minister,
        "previous": (before, previous) if previous else None,
    }


# The reads of each kind of page.
READS = {
    "wet": law,
    "artikel": article,
    "uitspraak": judgment,
    "kamerstuk": paper,
    "dossier": dossier,
    "lid": member,
    "fractie": faction,
    "kabinet": cabinet,
    "commissie": committee,
}
