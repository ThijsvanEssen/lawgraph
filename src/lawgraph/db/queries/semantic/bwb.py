"""The reads and updates of the semantic phase for BWB: the aliases and articles of the
instruments, the annexes, the amending versions and the Staatsblad and Staatscourant
publications a step resolves against them.

A read whose order ArangoDB left open comes in the order of the keys, so a run reads the same
rows in the same order every time.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg import sql
from psycopg.types.json import Json

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RELATION_REFERS_TO,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import (
    absent_sql,
    differs_sql,
    nonempty_sql,
    present_sql,
    slim_sql,
)
from lawgraph.db.store import _rounds

# The fields an article is filtered on by law: generated columns of ``articles``.
_LAW_FIELDS = ("bwb_id", "celex")


def law_articles(store: Store, field: str, law_id: str) -> Iterator[dict[str, Any]]:
    """``{key, number, last_number, stub}`` of every article of one law; *field* is
    ``bwb_id`` or ``celex``. A historical article has only ``last_number``."""
    if field not in _LAW_FIELDS:
        raise ValueError(f"Unknown law field: {field!r}")
    statement = sql.SQL(
        """
        SELECT key, props -> 'article_number' AS number,
               props -> 'last_article_number' AS last_number,
               stub IS TRUE AS stub
        FROM articles
        WHERE {field} = %(law_id)s
        ORDER BY key
        """
    ).format(field=sql.Identifier(field))
    return store.query(statement, {"law_id": law_id})


# The abbreviations of the instruments: ``core.aliases.code_aliases`` reads them.
def code_alias_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{short_title, aliases, bwb_id, celex, citation_title, title}`` of the instruments
    with a BWB id or a CELEX number, in the order of their keys."""
    return store.query(
        """
        SELECT props -> 'short_title' AS short_title, props -> 'aliases' AS aliases,
               props -> 'bwb_id' AS bwb_id, props -> 'celex' AS celex,
               props -> 'citation_title' AS citation_title, props -> 'title' AS title
        FROM instruments
        WHERE bwb_id IS NOT NULL OR celex IS NOT NULL
        ORDER BY key
        """
    )


def instrument_alias_rows(store: Store) -> Iterator[dict[str, Any]]:
    """``{bwb_id, celex, title, citation_title, citation_titles}`` of the instruments with a
    BWB id or a CELEX number, in the order of their keys."""
    return store.query(
        """
        SELECT props -> 'bwb_id' AS bwb_id, props -> 'celex' AS celex,
               props -> 'title' AS title, props -> 'citation_title' AS citation_title,
               props -> 'citation_titles' AS citation_titles
        FROM instruments
        WHERE bwb_id IS NOT NULL OR celex IS NOT NULL
        ORDER BY key
        """
    )


_BASIS_SQL = f"""
SELECT key, props -> 'bwb_id' AS bwb_id, props -> 'basis' AS basis
FROM instruments
WHERE lg_str(props -> 'source') = %(source)s AND {nonempty_sql("props -> 'basis'")}
ORDER BY key
"""


def regulations_with_basis(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, basis}`` of the BWB regulations that state a legal basis."""
    return store.query(_BASIS_SQL, {"source": SOURCE_BWB})


def instrument_keys_by_bwb_id(
    store: Store, bwb_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """``{_key, props: {bwb_id}}`` of the instruments with these *bwb_ids*."""
    return store.query(
        """
        SELECT json_build_object(
            '_key', key, 'props', json_build_object('bwb_id', props -> 'bwb_id')
        )
        FROM instruments
        WHERE bwb_id = ANY(%(bwb_ids)s)
        ORDER BY key
        """,
        {"bwb_ids": bwb_ids},
    )


def instrument_ids_by_bwb_id(store: Store, bwb_ids: list[str]) -> Iterator[Any]:
    """``{bwb_id, inst_id, inst_key}`` of the instruments with these *bwb_ids*."""
    return store.query(
        """
        SELECT props -> 'bwb_id' AS bwb_id, id AS inst_id, key AS inst_key
        FROM instruments
        WHERE bwb_id = ANY(%(bwb_ids)s)
        ORDER BY key
        """,
        {"bwb_ids": bwb_ids},
    )


def article_bwb_ids(store: Store) -> Iterator[Any]:
    """Every distinct BWB id that has article nodes in the graph, in order."""
    return store.query(
        "SELECT DISTINCT bwb_id FROM articles WHERE bwb_id IS NOT NULL ORDER BY bwb_id"
    )


_WITH_REFERENCES_SQL = f"""
SELECT {slim_sql("a", "bwb_id", "article_number", "references")}
FROM articles a
WHERE a.bwb_id = ANY(%(bwb_ids)s) AND {present_sql("a.props -> 'references'")}
ORDER BY a.key
"""


def articles_with_references(
    store: Store, bwb_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """The articles of *bwb_ids* that carry structured references."""
    return store.query(_WITH_REFERENCES_SQL, {"bwb_ids": bwb_ids})


def annex_keys(store: Store) -> Iterator[Any]:
    """The key of every annex."""
    return store.query("SELECT key FROM annexes ORDER BY key")


_TITLED_ANNEXES_SQL = f"""
SELECT key, props -> 'bwb_id' AS bwb_id, props -> 'label' AS label,
       props -> 'title' AS title
FROM annexes
WHERE {present_sql("props -> 'title'")} AND {present_sql("props -> 'bwb_id'")}
ORDER BY key
"""


def titled_annexes(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, label, title}`` of every annex with a title, by key."""
    return store.query(_TITLED_ANNEXES_SQL)


_NAMING_ANNEXES_SQL = f"""
SELECT json_build_object(
    'annex', n.value -> 'key',
    'article', {slim_sql("a", "bwb_id", "text", "article_number")}
)
FROM json_array_elements(%(names)s::json) WITH ORDINALITY AS n(value, ord)
JOIN articles a ON a.bwb_id = lg_str(n.value -> 'bwb_id')
WHERE strpos(lg_str(a.props -> 'text'), coalesce(n.value ->> 'name', '')) > 0
ORDER BY n.ord, a.key
"""


def articles_naming_annexes(
    store: Store, names: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Per ``{key, bwb_id, name}`` of *names*: the articles of that regulation whose text
    contains the name, as ``{annex, article}``; in the order of *names*, then by key."""
    return store.query(_NAMING_ANNEXES_SQL, {"names": Json(names)})


_MENTIONING_ANNEX_SQL = f"""
SELECT {slim_sql("a", "bwb_id", "text")}
FROM articles a
WHERE strpos(lower(lg_str(a.props -> 'text')), 'bijlage') > 0
ORDER BY a.key
"""


def articles_mentioning_annex(store: Store) -> Iterator[dict[str, Any]]:
    """The articles whose text contains the word "bijlage"."""
    return store.query(_MENTIONING_ANNEX_SQL)


# Sorted by article identity so that all versions of one article end up in the
# same chunk (needed to keep the earliest effective date per publication).
_AMENDING_VERSIONS_SQL = f"""
SELECT key, props -> 'bwb_id' AS bwb_id, props -> 'stam_id' AS stam_id,
       props -> 'effect' AS effect, props -> 'valid_from' AS valid_from,
       props -> 'source_publication' AS source_publication,
       props -> 'origin_publication' AS origin,
       props -> 'commencement_publication' AS commencement
FROM article_versions v
WHERE {present_sql("props -> 'origin_publication'")} AND v.stam_id IS NOT NULL
ORDER BY v.bwb_id NULLS FIRST, v.stam_id NULLS FIRST, v.key
"""


# One row per stored article; matched to the wanted (bwb_id, stam_id) pairs in Python.
_ARTICLES_BY_IDENTITY_SQL = """
SELECT key, props -> 'bwb_id' AS bwb_id, props -> 'stam_id' AS stam_id
FROM articles
WHERE bwb_id = ANY(%(bwb_ids)s) AND stam_id = ANY(%(stam_ids)s)
ORDER BY key
"""


_REGULATION_DOSSIERS_SQL = """
SELECT key,
       CASE WHEN json_typeof(props -> 'dossier_numbers') = 'array'
            THEN props -> 'dossier_numbers' ELSE '[]'::json END AS dossiers
FROM instruments
WHERE bwb_id IS NOT NULL
ORDER BY key
"""


def amending_article_versions(store: Store) -> Iterator[dict[str, Any]]:
    """The article versions that name the publication they came from, sorted by article
    identity."""
    return store.query(_AMENDING_VERSIONS_SQL)


def articles_by_identity(
    store: Store, bwb_ids: list[str], stam_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, stam_id}`` of the articles with a BWB id in *bwb_ids* and a stam id in
    *stam_ids*: every combination, not only the wanted pairs, by key."""
    return store.query(
        _ARTICLES_BY_IDENTITY_SQL, {"bwb_ids": bwb_ids, "stam_ids": stam_ids}
    )


def regulation_dossier_numbers(store: Store) -> Iterator[dict[str, Any]]:
    """``{key, dossiers}`` of every BWB regulation, with the parliamentary dossiers it
    lists (none too: its edges to dossiers it no longer lists go)."""
    return store.query(_REGULATION_DOSSIERS_SQL)


_CLASSIFIABLE_SQL = f"""
SELECT json_build_object('text', a.props -> 'text', 'edges', es.edges)
FROM articles a
JOIN (
    SELECT e.from_id, json_agg(json_build_object(
        'key', e.key,
        'start', e.doc -> 'meta' -> 'start',
        'end', e.doc -> 'meta' -> 'end'
    ) ORDER BY e.key) AS edges
    FROM edges e
    WHERE e.relation = %(relation)s AND e.from_collection = 'articles'
    GROUP BY e.from_id
) es ON es.from_id = a.id
WHERE {present_sql("a.props -> 'text'")}
ORDER BY a.key
"""


def articles_with_classifiable_edges(store: Store) -> Iterator[dict[str, Any]]:
    """Articles with their classifiable outgoing reference edges, articles and edges by
    key.

    Grouped per article so each article text crosses the wire once.
    """
    return store.query(_CLASSIFIABLE_SQL, {"relation": RELATION_REFERS_TO})


_CLASSIFICATION_DIFFERS = " OR ".join(
    differs_sql(stored, wanted)
    for stored, wanted in (
        ("t.doc -> 'semantic_type'", "u.value -> 'semantic_type'"),
        ("t.doc -> 'explanation'", "u.value -> 'explanation'"),
        ("t.doc -> 'meta' -> 'semantic_pattern'", "u.value -> 'pattern'"),
        (
            "t.doc -> 'meta' -> 'semantic_confidence'",
            "u.value -> 'semantic_confidence'",
        ),
    )
)

_CLASSIFICATIONS_SQL = f"""
UPDATE edges t SET doc = lg_merge(t.doc, json_build_object(
    'semantic_type', u.value -> 'semantic_type',
    'explanation', u.value -> 'explanation',
    'updated_at', %(now)s::text,
    'meta', lg_update(t.doc -> 'meta', json_build_object(
        'semantic_pattern', u.value -> 'pattern',
        'semantic_confidence', u.value -> 'semantic_confidence'
    ))
))
FROM json_array_elements(%(updates)s::json) AS u(value)
WHERE t.key = u.value ->> 'key' AND ({_CLASSIFICATION_DIFFERS})
RETURNING 1
"""


def update_edge_classifications(
    store: Store, batch: list[dict[str, Any]], now: str | None
) -> int:
    """Write the classifications of *batch* that differ from the stored ones; how many.

    ``updated_at`` says when a classification changed. Set on every run it made every
    edge differ from itself: 330,000 edges written again each time. The attributes merge
    into the edge (those it did not have after the others), its ``meta`` keeps its keys in
    order (D11). An edge twice in *batch* is written in rounds, in the order of *batch*.
    """
    updated = 0
    for round_ in _rounds(batch, "key"):
        rows = store.execute(
            _CLASSIFICATIONS_SQL, {"updates": Json(round_), "now": now}
        )
        updated += len(rows)
    return updated


_HAS_BWB_ID = present_sql("pub.props -> 'bwb_id'")
_NO_BWB_ID = absent_sql("pub.props -> 'bwb_id'")


def _text_longer_than(n: int) -> str:
    """A publication with a text of more than *n* characters."""
    return f"length(lg_str(pub.props -> 'text')) > {n}"


# The publications of a date or later when it is given; a publication without a date is
# before every date (as ArangoDB compared null with a string).
_SINCE = "(%(since_iso)s::text IS NULL OR pub.date >= %(since_iso)s)"

# Strategy 1: the instrument of the BWB id stored during normalization (the key settles two
# with one id).
_BY_BWB_ID = """
SELECT pub.id AS pub_id, pub.key AS pub_key, inst.id AS inst_id, inst.key AS inst_key,
       'bwb_id' AS match_type
FROM documents pub
CROSS JOIN LATERAL (
    SELECT i.id, i.key FROM instruments i
    WHERE i.bwb_id = lg_str(pub.props -> 'bwb_id')
    ORDER BY i.key
    LIMIT 1
) inst
WHERE pub.source = %(source)s AND {filters}
ORDER BY pub.key
"""

# Strategy 2: for a publication without a BWB id, the instrument whose citation title its
# title contains: the longest title the publication names wins (the key settles a tie).
#
# Testing every title against every publication is 13,000 x 120,000 ``strpos``. A title
# contained in another contains each of its pieces of _GRAM characters, so also the one
# piece of it that fewest titles share: only the instruments whose rarest piece the
# publication's title has are tested. A title shorter than a piece is tested against every
# publication, as before. Both titles are lowered once, and the props of a publication are
# read once (MATERIALIZED: an inlined CTE would read them again per test). Each candidate
# carries what the answer needs, so nothing is joined back; run with ``hash_joins``.
_GRAM = 6
_BY_TITLE = f"""
WITH insts AS MATERIALIZED (
    SELECT i.id, i.key, lower(i.citation_title) AS title,
           length(i.citation_title) AS len
    FROM instruments i
    WHERE i.citation_title IS NOT NULL {{instruments}}
),
inst_grams AS (
    SELECT s.id, substr(s.title, g, {_GRAM}) AS gram
    FROM insts s, generate_series(1, length(s.title) - {_GRAM - 1}) AS g
),
rarest AS (
    SELECT DISTINCT ON (g.id) g.id, g.gram
    FROM inst_grams g
    JOIN (SELECT gram, count(*) AS n FROM inst_grams GROUP BY gram) f USING (gram)
    ORDER BY g.id, f.n, g.gram NULLS FIRST
),
rare_insts AS (
    SELECT r.gram, s.id, s.key, s.title, s.len FROM rarest r JOIN insts s USING (id)
),
pubs AS MATERIALIZED (
    SELECT pub.id, pub.key, lower(coalesce(lg_str(pub.props -> 'title'), '')) AS title
    FROM documents pub
    WHERE pub.source = %(source)s AND {{filters}}
),
pub_grams AS (
    SELECT DISTINCT p.id, p.key, p.title, substr(p.title, g, {_GRAM}) AS gram
    FROM pubs p, generate_series(1, length(p.title) - {_GRAM - 1}) AS g
),
candidates AS (
    SELECT pg.id AS pub_id, pg.key AS pub_key, pg.title AS pub_title,
           s.id AS inst_id, s.key AS inst_key, s.title AS inst_title, s.len
    FROM pub_grams pg JOIN rare_insts s USING (gram)
    UNION ALL
    SELECT p.id, p.key, p.title, s.id, s.key, s.title, s.len
    FROM pubs p CROSS JOIN insts s
    WHERE length(s.title) < {_GRAM}
)
SELECT DISTINCT ON (pub_key) pub_id, pub_key, inst_id, inst_key, 'title' AS match_type
FROM candidates
WHERE strpos(pub_title, inst_title) > 0
ORDER BY pub_key, len DESC NULLS FIRST, inst_key
"""

_STAATSBLAD_BY_BWB_ID_SQL = _BY_BWB_ID.format(
    filters=f"{_text_longer_than(50)} AND {_HAS_BWB_ID}"
)
_STAATSBLAD_BY_TITLE_SQL = _BY_TITLE.format(
    instruments="", filters=f"{_text_longer_than(50)} AND {_NO_BWB_ID}"
)
_STAATSCOURANT_BY_BWB_ID_SQL = _BY_BWB_ID.format(filters=f"{_HAS_BWB_ID} AND {_SINCE}")
_STAATSCOURANT_BY_TITLE_SQL = _BY_TITLE.format(
    instruments="AND length(i.citation_title) > 5",
    filters=(f"{_NO_BWB_ID} AND length(lg_str(pub.props -> 'title')) > 5 AND {_SINCE}"),
)


def staatsblad_instrument_matches(store: Store) -> list[dict[str, Any]]:
    """``{pub_id, pub_key, inst_id, inst_key, match_type}`` per Staatsblad publication and
    the instrument it explains: by its BWB id, then by title for those without one."""
    params = {"source": SOURCE_STAATSBLAD}
    rows: list[dict[str, Any]] = []
    rows.extend(store.query(_STAATSBLAD_BY_BWB_ID_SQL, params))
    rows.extend(store.query(_STAATSBLAD_BY_TITLE_SQL, params, hash_joins=True))
    return rows


def staatscourant_instrument_matches(
    store: Store, since_date: str | None
) -> list[dict[str, Any]]:
    """``{pub_id, pub_key, inst_id, inst_key, match_type}`` per Staatscourant regulation and
    the instrument it explains: by its BWB id, then by title for those without one. With
    *since_date* only the publications of that date or later."""
    params = {"source": SOURCE_STAATSCOURANT, "since_iso": since_date or None}
    rows: list[dict[str, Any]] = []
    rows.extend(store.query(_STAATSCOURANT_BY_BWB_ID_SQL, params))
    rows.extend(store.query(_STAATSCOURANT_BY_TITLE_SQL, params, hash_joins=True))
    return rows


_STAATSCOURANT_TEXTS_SQL = f"""
SELECT pub.id AS pub_id, pub.key AS pub_key, pub.props -> 'text' AS text
FROM documents pub
WHERE pub.source = %(source)s AND {_text_longer_than(100)} AND {_SINCE}
ORDER BY pub.key
"""


def staatscourant_texts(store: Store, since_date: str | None) -> Iterator[Any]:
    """``{pub_id, pub_key, text}`` of the Staatscourant publications with a text, of
    *since_date* or later when it is given."""
    return store.query(
        _STAATSCOURANT_TEXTS_SQL,
        {"source": SOURCE_STAATSCOURANT, "since_iso": since_date or None},
    )


# A paper of the Staatsblad or the Staatscourant and the publication of the BWB of the same
# official id: ``documents/stb_stb_2019_33`` and ``instruments/stb_2019_33`` (the key of the
# paper is that of the publication after its source's prefix), by the keys alone.
_SAME_PUBLICATION_SQL = """
SELECT d.id AS doc_id, i.id AS inst_id
FROM documents d
JOIN instruments i ON i.id = 'instruments/' || substr(d.key, length(%(prefix)s) + 1)
WHERE d.source = %(source)s AND starts_with(d.key, %(prefix)s || %(prefix)s)
  AND i.kind = %(publication)s
ORDER BY d.id ASC NULLS LAST
"""


def same_publications(store: Store, source: str, prefix: str) -> list[dict[str, Any]]:
    """``{doc_id, inst_id}`` of every paper of *source* (keys ``<prefix><prefix>…``) whose
    publication of the BWB, of the same official id, is in the graph."""
    from lawgraph.core.bwb_xml import KIND_PUBLICATION

    return list(
        store.query(
            _SAME_PUBLICATION_SQL,
            {"source": source, "prefix": prefix, "publication": KIND_PUBLICATION},
        )
    )


def regulations_of_toestanden(
    store: Store, *, since_iso: str | None, after: str | None, limit: int | None
) -> list[str]:
    """The BWB ids of the stored toestanden, in order: those fetched at or after
    *since_iso*, past the BWB id *after*, at most *limit*."""
    return list(
        store.query(
            """
            SELECT external_id FROM raw_sources
            WHERE source = %(source)s AND kind = %(kind)s AND external_id IS NOT NULL
              AND (%(since)s::text IS NULL OR fetched_at >= %(since)s)
              AND (%(after)s::text IS NULL OR external_id > %(after)s)
            ORDER BY external_id
            LIMIT %(limit)s
            """,
            {
                "source": SOURCE_BWB,
                "kind": RAW_KIND_BWB_TOESTAND,
                "since": since_iso,
                "after": after,
                "limit": limit,
            },
        )
    )


def article_breadcrumbs(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, breadcrumb, caption}`` of the articles of these regulations."""
    return store.query(
        """
        SELECT key, bwb_id, props -> 'breadcrumb' AS breadcrumb,
               props -> 'caption' AS caption
        FROM articles WHERE bwb_id = ANY(%(ids)s::text[])
        ORDER BY bwb_id, key
        """,
        {"ids": bwb_ids},
    )
