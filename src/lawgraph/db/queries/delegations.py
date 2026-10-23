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
    COLLECTION_INSTRUMENTS,
    RELATION_BASED_ON,
    RELATION_REFERS_TO,
)
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore


def expired(alias: str) -> str:
    """Whether the instrument *alias* is no longer in force on the day ``%(today)s``: from
    ``props.date_expired`` on (the first day it was not, as the BWB gives it); one without
    it is in force. The list of instruments and the regulations under a law alike."""
    return f"coalesce(lg_str({alias}.props -> 'date_expired') <= %(today)s, false)"


def validity_clause(alias: str, param: str = "validity") -> str:
    """The condition on the instrument *alias* for the validity asked for (``in_force``,
    ``expired`` or ``all``, as the list of instruments has it), in ``%(param)s``."""
    return f"(%({param})s = 'all' OR {expired(alias)} = (%({param})s = 'expired'))"


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
        "date_signed",
        "article_count",
        "inbound_citation_count",
        "kind",
        "date_in_force",
        "date_expired",
    )
    props = ", ".join(f"'{f}', {alias}.props -> '{f}'" for f in fields)
    return (
        f"json_build_object('key', {alias}.key, 'id', {alias}.id, 'type', {alias}.type, "
        f"'labels', to_json({alias}.labels), 'props', json_build_object({props}))"
    )


def _article(alias: str, meta: str, display_name: str) -> str:
    """An article as the routes read it, with the meta of the edge at it."""
    return (
        f"json_build_object('id', {alias}.id, 'key', {alias}.key, 'article_number', "
        f"{alias}.article_number, 'display_name', {display_name}, 'meta', {meta})"
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
    WHERE NOT {expired("i")}
),
referring AS (
    SELECT a.bwb_id, json_agg({_article("a", "r.doc -> 'meta'", "a.props -> 'display_name'")}
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
                "today": dutch_today().isoformat(),
            },
        )
    )


# The parts of one regulation ``g`` (``id``, ``bwb_id``), each a part of a ``WITH`` inside a
# ``LATERAL`` over the regulations: every part reads its rows by the indexes of that one
# regulation, so a law with thousands of regulations costs thousands of small reads, never
# a join of two sets of all of them (the planner counts a regulation or two in each and
# joins them in a loop over the other: quadratic).

# The articles in force its preamble names (``BASED_ON``), each with the meta of its edge
# (one per article: the lowest key, as the edge writer keys one edge per pair) and its law:
# the edges of the regulation by the ``(from_id, relation, to_collection)`` index.
_NAMED = f"""
named AS MATERIALIZED (
    SELECT DISTINCT ON (x.id)
           x.id, x.key, x.bwb_id AS law, x.article_number, x.position,
           x.props -> 'display_name' AS display_name, e.doc -> 'meta' AS meta
    FROM {COLLECTION_EDGES} e
    JOIN {COLLECTION_ARTICLES} x ON x.id = e.to_id
    WHERE e.from_id = g.id AND e.relation = %(based_on)s
      AND e.to_collection = '{COLLECTION_ARTICLES}' AND x.repealed IS NOT TRUE
    ORDER BY x.id, e.key
)"""

# Its own articles in force, by the ``(bwb_id, …)`` index of the articles. Not their props:
# those hold the text; the parts below read the props of the articles they give alone.
_OWN = f"""
own AS MATERIALIZED (
    SELECT ra.id, ra.key, ra.article_number, ra.position
    FROM {COLLECTION_ARTICLES} ra
    WHERE ra.bwb_id = g.bwb_id AND ra.repealed IS NOT TRUE AND ra.stub IS NOT TRUE
)"""


def _referring(basis: str) -> str:
    """Per article of ``named`` that *basis* holds for, the articles of the regulation that
    refer to it, in the order of the regulation. ``refs``: the references of all its
    articles in one scan of the ``(from_id, relation, to_collection)`` index alone (it holds
    ``key`` and ``to_id``), never from the other end: the references into an article of the
    Awb are a hub. The row of an edge (its meta) and of an article (its name) only for the
    pairs found."""
    return f"""
refs AS MATERIALIZED (
    SELECT o.id, o.key, o.article_number, o.position, r.to_id, r.key AS edge_key
    FROM {COLLECTION_EDGES} r
    JOIN own o ON o.id = r.from_id
    WHERE r.from_id = ANY ((SELECT array_agg(id) FROM own)::text[])
      AND r.relation = %(refers_to)s AND r.to_collection = '{COLLECTION_ARTICLES}'
),
referring AS MATERIALIZED (
    SELECT p.basis_id, json_agg({_article("p", "m.doc -> 'meta'", "pa.props -> 'display_name'")}
                                ORDER BY p.position NULLS LAST, p.key) AS articles
    FROM (
        SELECT DISTINCT ON (b.id, o.id)
               b.id AS basis_id, o.id, o.key, o.article_number, o.position, o.edge_key
        FROM refs o
        JOIN named b ON b.id = o.to_id AND {basis}
        ORDER BY b.id, o.id, o.edge_key
    ) p
    JOIN {COLLECTION_EDGES} m ON m.key = p.edge_key
    JOIN {COLLECTION_ARTICLES} pa ON pa.id = p.id
    GROUP BY p.basis_id
)"""


# The articles of ``named`` that *basis* holds for, in the order of their law, each with
# ``referring``: a ``json_agg`` over ``named b`` with ``referring f`` joined to it.
_BASIS_ARTICLES = """json_agg(json_build_object(
        'id', b.id,
        'key', b.key,
        'article_number', b.article_number,
        'display_name', b.display_name,
        'meta', b.meta,
        'referring', coalesce(f.articles, '[]'::json)
    ) ORDER BY b.position NULLS LAST, b.key)"""

# The instrument of the law *alias*.law: the first by key with that BWB-id.
_LAW = f"""(
    SELECT i.id, i.key, i.type, i.labels, i.props FROM {COLLECTION_INSTRUMENTS} i
    WHERE i.bwb_id = {{alias}}.law ORDER BY i.key LIMIT 1
)"""

# The order of laws ``li``: by title, then key.
_LAW_ORDER = "coalesce(lower(li.props ->> 'citation_title'), lower(li.props ->> 'title'), ''), li.key"

# The other laws its preamble names (``also_based_on``): one entry per law, by title, with
# its articles in the order of that law.
_ALSO_BASED_ON = f"""(
    SELECT json_agg(json_build_object('instrument', {summary_json("li")},
                                      'articles', l.articles)
                    ORDER BY {_LAW_ORDER})
    FROM (
        SELECT c.law, json_agg({_article("c", "c.meta", "c.display_name")}
                               ORDER BY c.position NULLS LAST, c.key) AS articles
        FROM named c
        WHERE c.law IS DISTINCT FROM %(bwb)s
        GROUP BY c.law
    ) l
    JOIN LATERAL {_LAW.format(alias="l")} li ON true
)"""

# The regulations in force issued under its own articles (``sub_delegated``), one level
# down, by key, each with the articles of this regulation it names; not one that is issued
# under the law itself as well (an item of its own). The edges into each article in the
# ``(to_id, relation, from_collection)`` index alone (it holds ``key`` and ``from_id``); the
# rows of the edges and articles found after.
_SUB_DELEGATED = f"""(
    SELECT json_agg(json_build_object('instrument', {summary_json("si")},
                                      'articles', sg.articles)
                    ORDER BY si.key)
    FROM (
        SELECT u.sub_id,
               json_agg({_article("u", "m.doc -> 'meta'", "ua.props -> 'display_name'")}
                        ORDER BY u.position NULLS LAST, u.key) AS articles
        FROM (
            SELECT DISTINCT ON (s.from_id, o.id)
                   s.from_id AS sub_id, o.id, o.key, o.article_number, o.position,
                   s.key AS edge_key
            FROM {COLLECTION_EDGES} s
            JOIN own o ON o.id = s.to_id
            WHERE s.to_id = ANY ((SELECT array_agg(id) FROM own)::text[])
              AND s.relation = %(based_on)s
              AND s.from_collection = '{COLLECTION_INSTRUMENTS}'
              AND s.from_id NOT IN (SELECT from_id FROM based)
            ORDER BY s.from_id, o.id, s.key
        ) u
        JOIN {COLLECTION_EDGES} m ON m.key = u.edge_key
        JOIN {COLLECTION_ARTICLES} ua ON ua.id = u.id
        GROUP BY u.sub_id
    ) sg
    JOIN {COLLECTION_INSTRUMENTS} si ON si.id = sg.sub_id
    WHERE {validity_clause("si")}
)"""

# The regulations issued under any article in force of a law: by the edges into the articles
# of the law (their ``(bwb_id, …)`` index, then the ``(to_id, relation, from_collection)``
# index); the ones asked for by validity (``%(validity)s``).
_BASED = f"""
based AS MATERIALIZED (
    SELECT DISTINCT e.from_id
    FROM {COLLECTION_ARTICLES} a
    JOIN {COLLECTION_EDGES} e
      ON e.to_id = a.id AND e.relation = %(based_on)s
     AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
    WHERE a.bwb_id = %(bwb)s AND a.repealed IS NOT TRUE
)"""

# One row per regulation of the validity asked for, then the parts of each.
_DELEGATED_BY_LAW_SQL = f"""
WITH {_BASED},
regulations AS MATERIALIZED (
    SELECT i.id, i.key, i.type, i.labels, i.props, i.bwb_id
    FROM based b
    JOIN {COLLECTION_INSTRUMENTS} i ON i.id = b.from_id
    WHERE {validity_clause("i")}
)
SELECT {summary_json("g")} AS instrument,
       p.articles,
       coalesce(p.also_based_on, '[]'::json) AS also_based_on,
       coalesce(p.sub_delegated, '[]'::json) AS sub_delegated
FROM regulations g
CROSS JOIN LATERAL (
    WITH {_NAMED},
    {_OWN},
    {_referring("b.law = %(bwb)s")}
    SELECT (
        SELECT {_BASIS_ARTICLES}
        FROM named b
        LEFT JOIN referring f ON f.basis_id = b.id
        WHERE b.law = %(bwb)s
    ) AS articles,
    {_ALSO_BASED_ON} AS also_based_on,
    {_SUB_DELEGATED} AS sub_delegated
) p
"""

# The light form: the regulation and the articles of the law it names, nothing read of its
# own articles, its co-bases or the regulations under it.
_DELEGATED_SUMMARY_SQL = f"""
WITH {_BASED},
regulations AS MATERIALIZED (
    SELECT i.id, i.key, i.type, i.labels, i.props, i.bwb_id
    FROM based b
    JOIN {COLLECTION_INSTRUMENTS} i ON i.id = b.from_id
    WHERE {validity_clause("i")}
)
SELECT {summary_json("g")} AS instrument, p.articles
FROM regulations g
CROSS JOIN LATERAL (
    WITH {_NAMED}
    SELECT json_agg(json_build_object(
               'id', b.id, 'key', b.key, 'article_number', b.article_number,
               'display_name', b.display_name, 'meta', b.meta
           ) ORDER BY b.position NULLS LAST, b.key) AS articles
    FROM named b
    WHERE b.law = %(bwb)s
) p
"""

# How many regulations of the law are no longer in force: whatever validity was asked for.
_EXPIRED_COUNT_SQL = f"""
WITH {_BASED}
SELECT count(*) AS total
FROM based b
JOIN {COLLECTION_INSTRUMENTS} i ON i.id = b.from_id
WHERE {expired("i")}
"""


def get_delegated_by_law(
    store: GraphStore, bwb_id: str, validity: str = "in_force", summary: bool = False
) -> list[dict[str, Any]]:
    """The regulations ``BASED_ON`` any article of the law *bwb_id* of the *validity* (``in_force``,
    ``expired`` or ``all``), in no order: ``{instrument, articles, also_based_on,
    sub_delegated}``. ``articles``: the articles of
    the law its preamble names (``id``, ``key``, ``article_number``, ``display_name``,
    ``meta`` of the edge, ``referring``: the articles of the regulation that refer to it,
    each with the ``meta`` of that reference), in the order of the law. ``also_based_on``:
    the other laws it names (``instrument``, ``articles``), by title. ``sub_delegated``: the
    regulations of the validity issued under its articles that are not issued under the law
    itself (``instrument``, ``articles``: those of the regulation they name). Repealed
    articles are left out. With *summary* only ``instrument`` and ``articles`` without
    ``referring``. One query."""
    return list(
        store.query(
            _DELEGATED_SUMMARY_SQL if summary else _DELEGATED_BY_LAW_SQL,
            {
                "bwb": bwb_id.upper(),
                "based_on": RELATION_BASED_ON,
                "refers_to": RELATION_REFERS_TO,
                "today": dutch_today().isoformat(),
                "validity": validity,
            },
        )
    )


def count_expired_delegated(store: GraphStore, bwb_id: str) -> int:
    """How many regulations ``BASED_ON`` an article in force of the law *bwb_id* are no
    longer in force."""
    rows = store.query(
        _EXPIRED_COUNT_SQL,
        {
            "bwb": bwb_id.upper(),
            "based_on": RELATION_BASED_ON,
            "today": dutch_today().isoformat(),
        },
    )
    return int(next(iter(rows)))


# The basis of one regulation: the articles its preamble names, per law (one per law, by
# title), each with the meta of its edge and the articles of the regulation that refer to it.
_BASIS_SQL = f"""
SELECT {summary_json("li")} AS instrument, l.articles, {expired("li")} AS expired
FROM {COLLECTION_INSTRUMENTS} g
CROSS JOIN LATERAL (
    WITH {_NAMED},
    {_OWN},
    {_referring("true")}
    SELECT b.law, {_BASIS_ARTICLES} AS articles
    FROM named b
    LEFT JOIN referring f ON f.basis_id = b.id
    GROUP BY b.law
) l
JOIN LATERAL {_LAW.format(alias="l")} li ON true
WHERE g.id = %(instrument_id)s
ORDER BY {_LAW_ORDER}
"""


def get_basis(store: GraphStore, instrument_id: str) -> list[dict[str, Any]]:
    """The basis of the regulation *instrument_id* (``instruments/…``): per law its
    preamble names, by title, ``{instrument, articles, expired}`` (``expired``: the law is no
    longer in force) with ``articles`` as those of
    :func:`get_delegated_by_law` (in force, in the order of the law, with ``referring``:
    the articles of the regulation that refer to it). One query."""
    return list(
        store.query(
            _BASIS_SQL,
            {
                "instrument_id": instrument_id,
                "based_on": RELATION_BASED_ON,
                "refers_to": RELATION_REFERS_TO,
                "today": dutch_today().isoformat(),
            },
        )
    )
