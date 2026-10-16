"""What the sitemaps list (``commands/sitemaps.py``): per kind of page the node, the props
its readable address is made of (``core/readable_paths.path_of``) and the day it last
changed. Columns, the props that make a document's address, and the covering indexes of the edges.
Only pages that are indexed and have something to read (``api/seo/pages``: the same rule
per kind as its page's ``index``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    PUBLICATION_RELATIONS,
    RELATION_ABOUT,
    RELATION_MADE_IN,
    RELATION_PART_OF,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION
from lawgraph.core.publications import publication_indexed
from lawgraph.core.tk_records.kinds import KIND_AMENDMENT, KIND_MOTION
from lawgraph.db import GraphStore
from lawgraph.db.queries import member_role, seo, seo_links
from lawgraph.db.queries._json_sql import array_or_empty
from lawgraph.db.queries.instrument_scope import is_staatsblad_law

# The laws whose articles are listed: those whose articles are cited most.
TOP_LAWS = 150
# Motions and amendments with a decision since this day; publications and commitments
# since it too.
DECIDED_SINCE = "2018-01-01"
# The series whose publications are listed: the Staatsblad and the Tractatenblad (the
# Staatscourant is mostly regelingen of a day).
SERIES = ("stb", "trb")

# The day the version in force of each law began.
_IN_FORCE = f"""
    SELECT bwb_id, max(valid_from) AS valid_from
    FROM {COLLECTION_INSTRUMENT_VERSIONS}
    WHERE current
    GROUP BY bwb_id
"""


def laws(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every law with a BWB id that is no stub, with the day its version in force began;
    every EU act with an article (whose text was read: ``api/seo/pages/laws.law_page``),
    without a day (none is kept); and every law of the Staatsblad the BWB does not hold
    (yet), with the day it was published."""
    yield from store.query(
        f"""
        SELECT i.id, json_build_object('bwb_id', i.bwb_id, 'celex', i.celex) AS props,
               coalesce(v.valid_from, i.date_published) AS lastmod
        FROM {COLLECTION_INSTRUMENTS} i
        LEFT JOIN ({_IN_FORCE}) v ON v.bwb_id = i.bwb_id
        WHERE i.stub IS NOT TRUE
          AND (i.bwb_id IS NOT NULL
               OR (i.celex IS NOT NULL AND EXISTS (
                   SELECT 1 FROM {COLLECTION_ARTICLES} a
                   WHERE a.celex = i.celex AND a.stub IS NOT TRUE))
               OR {is_staatsblad_law("i")})
        ORDER BY i.id
        """
    )


def articles(store: GraphStore, top: int = TOP_LAWS) -> Iterator[dict[str, Any]]:
    """The articles in force with a text of the *top* laws by the citations of their
    articles, in the order of each law, with the day of the version in force of their
    law; then those of every law of the Staatsblad the BWB does not hold (yet), which no
    judgment cites yet, in the order of each law."""
    yield from _top_articles(store, top)
    yield from store.query(
        f"""
        SELECT a.id,
               json_build_object('official_id', a.official_id,
                                 'article_number', a.article_number) AS props,
               NULL::text AS lastmod
        FROM {COLLECTION_ARTICLES} a
        WHERE a.official_id IS NOT NULL AND a.stub IS NOT TRUE
          AND a.repealed IS NOT TRUE
          AND nullif(btrim(lg_str(a.props -> 'text')), '') IS NOT NULL
        ORDER BY a.official_id, a.position, a.id
        """
    )


def _top_articles(store: GraphStore, top: int) -> Iterator[dict[str, Any]]:
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
          AND nullif(btrim(lg_str(a.props -> 'text')), '') IS NOT NULL
        ORDER BY a.bwb_id, a.position, a.id
        """,
        {"top": top},
    )


def annexes(store: GraphStore) -> Iterator[dict[str, Any]]:
    """The annexes with a label and something to read (a description or entries) of the
    laws that are no stub, with the day the version in force of their law began."""
    yield from store.query(
        f"""
        SELECT x.id,
               json_build_object('bwb_id', x.bwb_id, 'label', lg_str(x.props -> 'label'))
                   AS props,
               v.valid_from AS lastmod
        FROM {COLLECTION_ANNEXES} x
        JOIN {COLLECTION_INSTRUMENTS} i ON i.bwb_id = x.bwb_id AND i.stub IS NOT TRUE
        LEFT JOIN ({_IN_FORCE}) v ON v.bwb_id = x.bwb_id
        WHERE lg_str(x.props -> 'label') IS NOT NULL
          AND lg_bool(x.props -> 'stub') IS NOT TRUE
          AND (lg_str(x.props -> 'description') IS NOT NULL
               OR json_array_length({array_or_empty("x.props -> 'entries'")}) > 0)
        ORDER BY x.id
        """
    )


def decided_cases(
    store: GraphStore, since: str = DECIDED_SINCE
) -> Iterator[dict[str, Any]]:
    """The zaken voted on since *since* (a decision with an outcome ABOUT them) but
    motions and amendments, whose documents are listed: a bill, a treaty, a budget. The last
    day one was taken on it is its lastmod."""
    yield from store.query(
        f"""
        SELECT c.id, json_build_object('number', lg_str(c.props -> 'number')) AS props,
               max(dec.date) AS lastmod
        FROM {COLLECTION_DECISIONS} dec
        JOIN edges a ON a.from_id = dec.id AND a.relation = %(about)s
            AND a.to_collection = '{COLLECTION_CASES}'
        JOIN {COLLECTION_CASES} c ON c.id = a.to_id
        WHERE dec.date >= %(since)s AND dec.passed IS NOT NULL
          AND NOT starts_with(coalesce(lg_str(c.props -> 'kind'), ''), '{KIND_MOTION}')
          AND NOT starts_with(coalesce(lg_str(c.props -> 'kind'), ''), '{KIND_AMENDMENT}')
        GROUP BY c.id
        ORDER BY c.id
        """,
        {"about": RELATION_ABOUT, "since": since},
    )


def decided_documents(
    store: GraphStore, kind: str, since: str = DECIDED_SINCE
) -> Iterator[dict[str, Any]]:
    """The documents of *kind* (``Motie``, ``Amendement``: the kinds that start with it) voted
    on since *since* whose page is indexed (``seo_links.DOCUMENT_INDEXED``): a decision with an
    outcome (not one withdrawn or postponed) is ABOUT a case the document is PART_OF. The
    last day one was taken on it is its lastmod."""
    yield from store.query(
        f"""
        SELECT d.id,
               json_build_object(
                   'dossier_number', any_value(d.dossier_number),
                   'dossier_suffix', any_value(d.props -> 'dossier_suffix'),
                   'sequence', any_value(d.props -> 'sequence'),
                   'number', any_value(d.props -> 'number')
               ) AS props,
               max(dec.date) AS lastmod
        FROM {COLLECTION_DECISIONS} dec
        JOIN edges a ON a.from_id = dec.id AND a.relation = %(about)s
            AND a.to_collection = '{COLLECTION_CASES}'
        JOIN edges p ON p.to_id = a.to_id AND p.relation = %(part_of)s
            AND p.from_collection = '{COLLECTION_DOCUMENTS}'
        JOIN {COLLECTION_DOCUMENTS} d ON d.id = p.from_id
        JOIN lg_document_light l ON l.id = d.id
        WHERE dec.date >= %(since)s AND dec.passed IS NOT NULL
          AND starts_with(d.kind, %(kind)s)
          AND {seo_links.DOCUMENT_INDEXED}
        GROUP BY d.id
        ORDER BY d.id
        """,
        {
            "about": RELATION_ABOUT,
            "part_of": RELATION_PART_OF,
            "since": since,
            "kind": kind,
        },
    )


def dossiers(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every dossier with a paper, with the day of its last activity."""
    yield from store.query(
        f"""
        SELECT x.id, json_build_object('label', x.label, 'number', x.number) AS props,
               x.last_activity AS lastmod
        FROM {COLLECTION_DOSSIERS} x
        WHERE EXISTS (SELECT 1 FROM {COLLECTION_DOCUMENTS} d
                      WHERE d.dossier_numbers @> ARRAY[x.label])
        ORDER BY x.id
        """
    )


def members(store: GraphStore) -> Iterator[dict[str, Any]]:
    """The members with a slug who have a role (``member_role``: sat in a chamber or held a
    post in a cabinet); no day of change (none is kept)."""
    yield from store.query(
        f"""
        SELECT m.id, json_build_object('slug', lg_str(m.props -> 'slug')) AS props,
               NULL AS lastmod
        FROM {COLLECTION_MEMBERS} m
        WHERE lg_str(m.props -> 'slug') IS NOT NULL AND {member_role.has_role("m")}
        ORDER BY m.id
        """
    )


def factions(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every faction with a name or an abbreviation, of both chambers, with the day one of
    its seats last changed."""
    yield from store.query(
        f"""
        SELECT id, '{{}}'::json AS props, lg_str(props -> 'seats_changed_on') AS lastmod
        FROM {COLLECTION_FACTIONS}
        WHERE coalesce(nullif(btrim(lg_str(props -> 'name')), ''),
                       nullif(btrim(lg_str(props -> 'abbreviation')), '')) IS NOT NULL
        ORDER BY id
        """
    )


def cabinets(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every cabinet, with the day it last changed: its end, else the start of its last
    phase, else its beëdiging."""
    yield from store.query(
        f"""
        SELECT id, '{{}}'::json AS props,
               coalesce(
                   lg_str(props -> 'to_date'),
                   (SELECT max(lg_str(p -> 'from_date'))
                    FROM json_array_elements(
                        {array_or_empty("props -> 'phases'")}) p),
                   lg_str(props -> 'from_date')
               ) AS lastmod
        FROM {COLLECTION_CABINETS}
        ORDER BY id
        """
    )


def committees(store: GraphStore) -> Iterator[dict[str, Any]]:
    """Every committee with a slug and a name, of both chambers; no day of change (none is
    kept)."""
    yield from store.query(
        f"""
        SELECT id, json_build_object('slug', lg_str(props -> 'slug')) AS props,
               NULL AS lastmod
        FROM {COLLECTION_COMMITTEES}
        WHERE lg_str(props -> 'slug') IS NOT NULL
          AND coalesce(nullif(btrim(lg_str(props -> 'name')), ''),
                       nullif(btrim(lg_str(props -> 'title')), '')) IS NOT NULL
        ORDER BY id
        """
    )


def note_id_sql(official: str) -> str:
    """SQL: the id of the nota van toelichting of the KOOP id *official* (an expression),
    as ``core.publications.note_key`` makes its key: ``documents/stb_stb_2026_94``."""
    return (
        f"'{COLLECTION_DOCUMENTS}/' || split_part({official}, '-', 1)"
        f" || '_' || replace({official}, '-', '_')"
    )


def publications(
    store: GraphStore, since: str = DECIDED_SINCE
) -> Iterator[dict[str, Any]]:
    """The publications in the Staatsblad and the Tractatenblad since *since* whose page is
    indexed (``core.publications.publication_indexed``): a title of their own (their nota
    van toelichting) or a regulation they change by name (``seo.named_changes_sql``). The
    day they were published is their lastmod."""
    rows = store.query(
        f"""
        WITH listed AS (
            SELECT i.id, lg_str(i.props -> 'official_id') AS official,
                   i.date_published
            FROM {COLLECTION_INSTRUMENTS} i
            WHERE i.kind = '{KIND_PUBLICATION}' AND i.date_published >= %(since)s
              AND split_part(lg_str(i.props -> 'official_id'), '-', 1)
                  = ANY(%(series)s::text[])
        )
        SELECT l.id, json_build_object('official_id', l.official) AS props,
               l.date_published AS lastmod,
               lg_str(light.props -> 'title') AS title,
               EXISTS (
                   SELECT 1
                   FROM ({seo.named_changes_sql("ARRAY[l.id, note.id]")}) c
               ) AS changes_a_named_regulation
        FROM listed l
        LEFT JOIN {COLLECTION_DOCUMENTS} note ON note.id = {note_id_sql("l.official")}
        LEFT JOIN lg_document_light light ON light.id = note.id
        ORDER BY l.id
        """,
        {
            "since": since,
            "series": list(SERIES),
            "changes": list(PUBLICATION_RELATIONS),
        },
    )
    for row in rows:
        if publication_indexed(row["title"], row["changes_a_named_regulation"]):
            yield row


def commitments(
    store: GraphStore, since: str = DECIDED_SINCE
) -> Iterator[dict[str, Any]]:
    """The commitments made since *since* that have a text, with the day they were made."""
    yield from store.query(
        f"""
        SELECT id, json_build_object('number', number) AS props, made_on AS lastmod
        FROM {COLLECTION_COMMITMENTS}
        WHERE made_on >= %(since)s AND lg_str(props -> 'text') IS NOT NULL
        ORDER BY id
        """,
        {"since": since},
    )


def activities(
    store: GraphStore, since: str = DECIDED_SINCE
) -> Iterator[dict[str, Any]]:
    """The activities held since *since* with something to read: a document (a stenogram, a
    verslag, a motion) or a commitment made in it (``MADE_IN``), with their day."""
    yield from store.query(
        f"""
        SELECT a.id, json_build_object('number', lg_str(a.props -> 'number')) AS props,
               a.date AS lastmod
        FROM {COLLECTION_ACTIVITIES} a
        WHERE a.date >= %(since)s
          AND EXISTS (
              SELECT 1 FROM {COLLECTION_EDGES} e
              WHERE e.to_id = a.id AND e.relation = %(made_in)s
                AND e.from_collection = ANY(%(made)s::text[])
          )
        ORDER BY a.id
        """,
        {
            "since": since,
            "made_in": RELATION_MADE_IN,
            "made": [COLLECTION_DOCUMENTS, COLLECTION_COMMITMENTS],
        },
    )
