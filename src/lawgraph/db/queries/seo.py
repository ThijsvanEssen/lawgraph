"""What the server HTML of a readable address shows (``api/seo``): the node it names and
the sources it links to, each from light reads (columns, ``lg_judgment_light``,
``lg_document_light``, the covering indexes of the edges). The text of a judgment or a
paper is never read; that of an article is (it is the page).
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_EXPLAINS,
    RELATION_REFERS_TO,
)
from lawgraph.core.readable_paths import Pad, focus_of_pad
from lawgraph.db import GraphStore
from lawgraph.db.queries import lookup
from lawgraph.db.queries.decisions import get_document_decisions

# How many sources a page links to of each kind: enough for a reader and a crawler, few
# enough for a page of a few tens of KB.
LINKS = 20
# The papers of a dossier a page lists, newest first.
PAPERS = 200
# The articles of a law its table of contents lists, in their order.
ARTICLES = 5000


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
    """An article (its props, its text too), its law, the judgments that cite it (the
    most cited first) and how many judgments and papers cite or explain it."""
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
    judgments = list(
        store.query(
            f"""
            SELECT j.id, l.props AS light
            FROM edges e
            JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
            LEFT JOIN lg_judgment_light l ON l.id = j.id
            WHERE e.to_id = %(id)s AND e.relation = %(refers)s
              AND e.from_collection = '{COLLECTION_JUDGMENTS}'
            ORDER BY j.inbound_citation_count DESC NULLS LAST, j.key DESC
            LIMIT %(limit)s
            """,
            {"id": node_id, "refers": RELATION_REFERS_TO, "limit": LINKS},
        )
    )
    counts = _first(
        store,
        f"""
        SELECT
          (SELECT count(*) FROM edges e WHERE e.to_id = %(id)s
             AND e.relation = %(refers)s
             AND e.from_collection = '{COLLECTION_JUDGMENTS}')::int AS judgments,
          (SELECT count(*) FROM edges e WHERE e.to_id = %(id)s
             AND e.relation IN (%(refers)s, %(explains)s)
             AND e.from_collection = '{COLLECTION_DOCUMENTS}')::int AS papers
        """,
        {"id": node_id, "refers": RELATION_REFERS_TO, "explains": RELATION_EXPLAINS},
    )
    return {**row, "judgments": judgments, "counts": counts}


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


# The reads of each kind of page.
READS = {
    "wet": law,
    "artikel": article,
    "uitspraak": judgment,
    "kamerstuk": paper,
    "dossier": dossier,
}
