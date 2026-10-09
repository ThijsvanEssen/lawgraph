"""What the sitemaps list (``commands/sitemaps.py``): per kind of page the node, the props
its readable address is made of (``core/readable_paths.path_of``) and the day it last
changed. Columns, the props that make a paper's address, and the covering indexes of the edges.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.db import GraphStore

# The laws whose articles are listed: those whose articles are cited most.
TOP_LAWS = 150
# Motions and amendments with a decision since this day.
DECIDED_SINCE = "2018-01-01"

# The day the version in force of each law began.
_IN_FORCE = f"""
    SELECT bwb_id, max(valid_from) AS valid_from
    FROM {COLLECTION_INSTRUMENT_VERSIONS}
    WHERE current
    GROUP BY bwb_id
"""


def laws(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every law with a BWB id that is no stub, with the day its version in force began."""
    yield from store.query(
        f"""
        SELECT i.id, json_build_object('bwb_id', i.bwb_id) AS props,
               v.valid_from AS lastmod
        FROM {COLLECTION_INSTRUMENTS} i
        LEFT JOIN ({_IN_FORCE}) v ON v.bwb_id = i.bwb_id
        WHERE i.bwb_id IS NOT NULL AND i.stub IS NOT TRUE
        ORDER BY i.id
        """
    )


def articles(store: GraphStore, top: int = TOP_LAWS) -> Iterator[dict[str, Any]]:
    """The articles in force of the *top* laws by the citations of their articles, in the
    order of each law, with the day of the version in force of their law."""
    yield from store.query(
        f"""
        WITH top AS (
            SELECT bwb_id
            FROM {COLLECTION_ARTICLES}
            WHERE bwb_id IS NOT NULL AND stub IS NOT TRUE
            GROUP BY bwb_id
            ORDER BY sum(coalesce(inbound_citation_count, 0)) DESC NULLS LAST, bwb_id
            LIMIT %(top)s
        )
        SELECT a.id,
               json_build_object('bwb_id', a.bwb_id, 'article_number', a.article_number)
                   AS props,
               v.valid_from AS lastmod
        FROM {COLLECTION_ARTICLES} a
        JOIN top ON top.bwb_id = a.bwb_id
        LEFT JOIN ({_IN_FORCE}) v ON v.bwb_id = a.bwb_id
        WHERE a.stub IS NOT TRUE AND a.repealed IS NOT TRUE
        ORDER BY a.bwb_id, a.position, a.id
        """,
        {"top": top},
    )


def decided_papers(
    store: GraphStore, kind: str, since: str = DECIDED_SINCE
) -> Iterator[dict[str, Any]]:
    """The papers of *kind* (``Motie``, ``Amendement``: the kinds that start with it) voted
    on since *since*: a decision with an outcome (not one withdrawn or postponed) is ABOUT
    a case the paper is PART_OF. The last day one was taken on it is its lastmod."""
    yield from store.query(
        f"""
        SELECT doc.id,
               json_build_object(
                   'dossier_number', any_value(doc.dossier_number),
                   'dossier_suffix', any_value(doc.props -> 'dossier_suffix'),
                   'sequence', any_value(doc.props -> 'sequence'),
                   'number', any_value(doc.props -> 'number')
               ) AS props,
               max(dec.date) AS lastmod
        FROM {COLLECTION_DECISIONS} dec
        JOIN edges a ON a.from_id = dec.id AND a.relation = %(about)s
            AND a.to_collection = '{COLLECTION_CASES}'
        JOIN edges p ON p.to_id = a.to_id AND p.relation = %(part_of)s
            AND p.from_collection = '{COLLECTION_DOCUMENTS}'
        JOIN {COLLECTION_DOCUMENTS} doc ON doc.id = p.from_id
        WHERE dec.date >= %(since)s AND dec.passed IS NOT NULL
          AND starts_with(doc.kind, %(kind)s)
        GROUP BY doc.id
        ORDER BY doc.id
        """,
        {
            "about": RELATION_ABOUT,
            "part_of": RELATION_PART_OF,
            "since": since,
            "kind": kind,
        },
    )


def dossiers(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every dossier, with the day of its last activity."""
    yield from store.query(
        f"""
        SELECT id, json_build_object('label', label, 'number', number) AS props,
               last_activity AS lastmod
        FROM {COLLECTION_DOSSIERS}
        ORDER BY id
        """
    )
