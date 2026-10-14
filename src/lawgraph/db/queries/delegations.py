"""The regulations in force issued under an article, or under any article in force of a law, and
the basis of a regulation: ``BASED_ON`` edges, with the articles of each regulation that refer
to its basis.

``semantic bwb-grondslagen`` writes ``Instrument --BASED_ON--> Article`` from the "Gelet op"
paragraph of a regulation, with the text of that reference in ``meta.text`` ("16, eerste en
zevende lid") and ``meta.basis_kind`` (whether the article gives the power or is only named).
The articles of such a regulation that name the article ("als bedoeld in artikel 16, eerste
lid, van de wet") are its ``REFERS_TO`` edges into it.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    RELATION_BASED_ON,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore


def _in_force(alias: str) -> str:
    """Whether the regulation *alias* is in force: its versions are not all closed (none
    ``current``: repealed); one without versions counts as in force. One probe of the
    ``(bwb_id, current)`` index of the versions."""
    return f"""(
    SELECT bool_or(v.current IS TRUE) FROM {COLLECTION_INSTRUMENT_VERSIONS} v
    WHERE v.bwb_id = {alias}.bwb_id
) IS NOT FALSE"""


def summary_json(alias: str) -> str:
    """An instrument as ``InstrumentSummaryDTO.from_document`` and the routes read it: the
    props it shows, not the whole node (``basis``, ``celex_refs`` of a large law)."""
    fields = (
        "bwb_id",
        "celex",
        "title",
        "citation_title",
        "short_title",
        "abbreviation",
        "display_name",
        "article_count",
        "inbound_citation_count",
        "kind",
        "date_in_force",
    )
    props = ", ".join(f"'{f}', {alias}.props -> '{f}'" for f in fields)
    return (
        f"json_build_object('_key', {alias}.key, '_id', {alias}.id, 'type', {alias}.type, "
        f"'labels', to_json({alias}.labels), 'props', json_build_object({props}))"
    )


def _article(alias: str, meta: str) -> str:
    """An article as the routes read it, with the meta of the edge at it."""
    return (
        f"json_build_object('id', {alias}.id, 'key', {alias}.key, 'article_number', "
        f"{alias}.article_number, 'display_name', {alias}.props -> 'display_name', "
        f"'meta', {meta})"
    )


# One row per regulation: the regulation, the meta of its edge (one per regulation: the
# lowest key, as the edge writer keys one edge per pair) and the articles of the regulation
# that refer to the article, in the order of the regulation. Both passes read the edges of
# the article by the ``(to_id, relation, from_collection)`` index; only the articles of the
# regulations found are read.
_DELEGATED_SQL = f"""
WITH based AS (
    SELECT DISTINCT ON (e.from_id) e.from_id, e.doc -> 'meta' AS meta
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = %(article_id)s AND e.relation = %(based_on)s
      AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
    ORDER BY e.from_id, e.key
),
regulations AS (
    SELECT i.id, i.key, i.type, i.labels, i.props, i.bwb_id, b.meta
    FROM based b JOIN {COLLECTION_INSTRUMENTS} i ON i.id = b.from_id
    WHERE {_in_force("i")}
),
referring AS (
    SELECT a.bwb_id, json_agg({_article("a", "r.doc -> 'meta'")}
                              ORDER BY a.position NULLS LAST, a.key) AS articles
    FROM {COLLECTION_EDGES} r
    JOIN {COLLECTION_ARTICLES} a ON a.id = r.from_id
    WHERE r.to_id = %(article_id)s AND r.relation = %(refers_to)s
      AND r.from_collection = '{COLLECTION_ARTICLES}'
      AND a.repealed IS NOT TRUE
      AND a.bwb_id IN (SELECT g.bwb_id FROM regulations g)
    GROUP BY a.bwb_id
)
SELECT {summary_json("g")} AS instrument,
       g.meta,
       coalesce(f.articles, '[]'::json) AS articles
FROM regulations g
LEFT JOIN referring f ON f.bwb_id = g.bwb_id
ORDER BY g.key
"""


def get_delegated_regulations(
    store: GraphStore, article_id: str
) -> list[dict[str, Any]]:
    """The regulations in force ``BASED_ON`` the article, by key:
    ``{instrument, meta, articles}`` with ``articles`` the articles of the regulation that refer to it (``id``, ``key``,
    ``article_number``, ``display_name``, ``meta`` of the reference). One query."""
    return list(
        store.query(
            _DELEGATED_SQL,
            {
                "article_id": article_id,
                "based_on": RELATION_BASED_ON,
                "refers_to": RELATION_REFERS_TO,
            },
        )
    )


# The articles in force of the regulations of ``regulations`` (``id``, ``bwb_id``), each with
# the id of its regulation: by the ``(bwb_id, …)`` index of the articles. A part of a ``WITH``
# that has ``regulations`` before it.
_REGULATION_ARTICLES = f"""
regulation_articles AS MATERIALIZED (
    SELECT g.id AS reg_id, ra.id, ra.key, ra.article_number, ra.position, ra.props
    FROM regulations g
    JOIN {COLLECTION_ARTICLES} ra ON ra.bwb_id = g.bwb_id
    WHERE ra.repealed IS NOT TRUE AND ra.stub IS NOT TRUE
)"""

# Per pair of ``based`` (``from_id``: the regulation, ``id``: the article it names) the
# articles of the regulation that refer to that article, in the order of the regulation: each
# article of the regulation probes its own references once (the ``(from_id, relation,
# to_collection)`` index, which holds ``to_id``).
_REFERRING = f"""
referring AS (
    SELECT p.reg_id, p.basis_id, json_agg({_article("p", "p.meta")}
                                          ORDER BY p.position NULLS LAST, p.key) AS articles
    FROM (
        SELECT DISTINCT ON (ra.reg_id, b.id, ra.id)
               ra.reg_id, b.id AS basis_id, ra.id, ra.key, ra.article_number,
               ra.position, ra.props, r.doc -> 'meta' AS meta
        FROM regulation_articles ra
        JOIN {COLLECTION_EDGES} r
          ON r.from_id = ra.id AND r.relation = %(refers_to)s
         AND r.to_collection = '{COLLECTION_ARTICLES}'
        JOIN based b ON b.from_id = ra.reg_id AND b.id = r.to_id
        ORDER BY ra.reg_id, b.id, ra.id, r.key
    ) p
    GROUP BY p.reg_id, p.basis_id
)"""

# Per regulation the other laws its preamble names (``also_based_on``): one entry per law, by
# title, with its articles in the order of that law. The edges of the regulation by the
# ``(from_id, relation, to_collection)`` index.
_ALSO_BASED_ON = f"""
co AS (
    SELECT DISTINCT ON (g.id, x.id)
           g.id AS reg_id, x.bwb_id AS law, x.id, x.key, x.article_number, x.position,
           x.props, e.doc -> 'meta' AS meta
    FROM regulations g
    JOIN {COLLECTION_EDGES} e
      ON e.from_id = g.id AND e.relation = %(based_on)s
     AND e.to_collection = '{COLLECTION_ARTICLES}'
    JOIN {COLLECTION_ARTICLES} x ON x.id = e.to_id
    WHERE x.bwb_id IS DISTINCT FROM %(bwb)s AND x.repealed IS NOT TRUE
    ORDER BY g.id, x.id, e.key
),
co_laws AS (
    SELECT c.reg_id, c.law, json_agg({_article("c", "c.meta")}
                                     ORDER BY c.position NULLS LAST, c.key) AS articles
    FROM co c
    GROUP BY c.reg_id, c.law
),
also_based_on AS (
    SELECT l.reg_id, json_agg(json_build_object(
        'instrument', {summary_json("li")}, 'articles', l.articles
    ) ORDER BY coalesce(lower(li.props ->> 'citation_title'), lower(li.props ->> 'title'), ''),
      li.key) AS laws
    FROM co_laws l
    JOIN LATERAL (
        SELECT i.id, i.key, i.type, i.labels, i.props FROM {COLLECTION_INSTRUMENTS} i
        WHERE i.bwb_id = l.law ORDER BY i.key LIMIT 1
    ) li ON true
    GROUP BY l.reg_id
)"""

# Per regulation the regulations in force issued under its articles (``sub_delegated``), one
# level down, each with the articles of the regulation it names; not one that is issued
# under the law itself as well (an item of its own). The edges into each article by the
# ``(to_id, relation, from_collection)`` index.
_SUB_DELEGATED = f"""
sub AS (
    SELECT DISTINCT ON (ra.reg_id, s.from_id, ra.id)
           ra.reg_id, s.from_id AS sub_id, ra.id, ra.key, ra.article_number,
           ra.position, ra.props, s.doc -> 'meta' AS meta
    FROM regulation_articles ra
    JOIN {COLLECTION_EDGES} s
      ON s.to_id = ra.id AND s.relation = %(based_on)s
     AND s.from_collection = '{COLLECTION_INSTRUMENTS}'
    WHERE s.from_id NOT IN (SELECT from_id FROM based)
    ORDER BY ra.reg_id, s.from_id, ra.id, s.key
),
sub_grouped AS (
    SELECT u.reg_id, u.sub_id, json_agg({_article("u", "u.meta")}
                                        ORDER BY u.position NULLS LAST, u.key) AS articles
    FROM sub u
    GROUP BY u.reg_id, u.sub_id
),
sub_delegated AS (
    SELECT sg.reg_id, json_agg(json_build_object(
        'instrument', {summary_json("si")}, 'articles', sg.articles
    ) ORDER BY si.key) AS regulations
    FROM sub_grouped sg
    JOIN {COLLECTION_INSTRUMENTS} si ON si.id = sg.sub_id
    WHERE {_in_force("si")}
    GROUP BY sg.reg_id
)"""

# One row per regulation in force issued under any article in force of a law: the regulation
# and the articles of the law its preamble names, each with the meta of its edge (one per
# pair: the lowest key) and the articles of the regulation that refer to it, in the order of
# the law; the other laws it names and the regulations issued under it in turn. The articles
# of the law by their ``(bwb_id, …)`` index, their edges by the ``(to_id, relation,
# from_collection)`` index: one probe per article, in the query.
_DELEGATED_BY_LAW_SQL = f"""
WITH based AS (
    SELECT DISTINCT ON (e.from_id, a.id)
           e.from_id, a.id, a.key, a.article_number, a.position, a.props,
           e.doc -> 'meta' AS meta
    FROM {COLLECTION_ARTICLES} a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.id AND e.relation = %(based_on)s
     AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
    WHERE a.bwb_id = %(bwb)s AND a.repealed IS NOT TRUE
    ORDER BY e.from_id, a.id, e.key
),
regulations AS MATERIALIZED (
    SELECT i.id, i.key, i.type, i.labels, i.props, i.bwb_id
    FROM (SELECT DISTINCT from_id FROM based) b
    JOIN {COLLECTION_INSTRUMENTS} i ON i.id = b.from_id
    WHERE {_in_force("i")}
),
{_REGULATION_ARTICLES},
{_REFERRING},
{_ALSO_BASED_ON},
{_SUB_DELEGATED},
grouped AS (
    SELECT b.from_id, json_agg(json_build_object(
        'id', b.id,
        'key', b.key,
        'article_number', b.article_number,
        'display_name', b.props -> 'display_name',
        'meta', b.meta,
        'referring', coalesce(f.articles, '[]'::json)
    ) ORDER BY b.position NULLS LAST, b.key) AS articles
    FROM based b
    JOIN regulations g ON g.id = b.from_id
    LEFT JOIN referring f ON f.reg_id = b.from_id AND f.basis_id = b.id
    GROUP BY b.from_id
)
SELECT {summary_json("g")} AS instrument,
       gr.articles,
       coalesce(a.laws, '[]'::json) AS also_based_on,
       coalesce(s.regulations, '[]'::json) AS sub_delegated
FROM regulations g
JOIN grouped gr ON gr.from_id = g.id
LEFT JOIN also_based_on a ON a.reg_id = g.id
LEFT JOIN sub_delegated s ON s.reg_id = g.id
"""


def get_delegated_by_law(store: GraphStore, bwb_id: str) -> list[dict[str, Any]]:
    """The regulations ``BASED_ON`` any article of the law *bwb_id*, in no order:
    ``{instrument, articles, also_based_on, sub_delegated}``. ``articles``: the articles of
    the law its preamble names (``id``, ``key``, ``article_number``, ``display_name``,
    ``meta`` of the edge, ``referring``: the articles of the regulation that refer to it,
    each with the ``meta`` of that reference), in the order of the law. ``also_based_on``:
    the other laws it names (``instrument``, ``articles``), by title. ``sub_delegated``: the
    regulations in force issued under its articles that are not issued under the law
    itself (``instrument``, ``articles``: those of the regulation they name). Repealed
    articles and regulations are left out. One query."""
    return list(
        store.query(
            _DELEGATED_BY_LAW_SQL,
            {
                "bwb": bwb_id.upper(),
                "based_on": RELATION_BASED_ON,
                "refers_to": RELATION_REFERS_TO,
            },
        )
    )


# The basis of one regulation: the articles its preamble names, per law (one per law, by
# title), each with the meta of its edge and the articles of the regulation that refer to it.
# Its edges by the ``(from_id, relation, to_collection)`` index; its own articles by their
# ``(bwb_id, …)`` index.
_BASIS_SQL = f"""
WITH regulations AS MATERIALIZED (
    SELECT i.id, i.bwb_id FROM {COLLECTION_INSTRUMENTS} i WHERE i.id = %(instrument_id)s
),
based AS (
    SELECT DISTINCT ON (x.id)
           e.from_id, x.id, x.key, x.bwb_id AS law, x.article_number, x.position,
           x.props, e.doc -> 'meta' AS meta
    FROM regulations g
    JOIN {COLLECTION_EDGES} e
      ON e.from_id = g.id AND e.relation = %(based_on)s
     AND e.to_collection = '{COLLECTION_ARTICLES}'
    JOIN {COLLECTION_ARTICLES} x ON x.id = e.to_id
    WHERE x.repealed IS NOT TRUE
    ORDER BY x.id, e.key
),
{_REGULATION_ARTICLES},
{_REFERRING},
laws AS (
    SELECT b.law, json_agg(json_build_object(
        'id', b.id,
        'key', b.key,
        'article_number', b.article_number,
        'display_name', b.props -> 'display_name',
        'meta', b.meta,
        'referring', coalesce(f.articles, '[]'::json)
    ) ORDER BY b.position NULLS LAST, b.key) AS articles
    FROM based b
    LEFT JOIN referring f ON f.basis_id = b.id
    GROUP BY b.law
)
SELECT {summary_json("li")} AS instrument, l.articles
FROM laws l
JOIN LATERAL (
    SELECT i.id, i.key, i.type, i.labels, i.props FROM {COLLECTION_INSTRUMENTS} i
    WHERE i.bwb_id = l.law ORDER BY i.key LIMIT 1
) li ON true
ORDER BY coalesce(lower(li.props ->> 'citation_title'), lower(li.props ->> 'title'), ''), li.key
"""


def get_basis(store: GraphStore, instrument_id: str) -> list[dict[str, Any]]:
    """The basis of the regulation *instrument_id* (``instruments/…``): per law its
    preamble names, by title, ``{instrument, articles}`` with ``articles`` as those of
    :func:`get_delegated_by_law` (in force, in the order of the law, with ``referring``:
    the articles of the regulation that refer to it). One query."""
    return list(
        store.query(
            _BASIS_SQL,
            {
                "instrument_id": instrument_id,
                "based_on": RELATION_BASED_ON,
                "refers_to": RELATION_REFERS_TO,
            },
        )
    )
