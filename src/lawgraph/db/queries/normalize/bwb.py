"""The graph reads and updates of the normalize phase for BWB: article identities and
versions, the places stored for them, and the short titles set in place.

A read whose order ArangoDB left open comes in the order of the keys."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from psycopg.types.json import Json

from lawgraph.db.counting import Store
from lawgraph.db.queries.semantic import differs_sql, nonempty_sql
from lawgraph.db.store import _rounds

# Per row: the short title (json, null when it has none) and the aliases when there are
# any (else SQL NULL).
_ABBREVIATION_ROWS = f"""
SELECT u.value ->> 'key' AS key,
       u.value -> 'short_title' AS short_title,
       CASE WHEN {nonempty_sql("u.value -> 'aliases'")} THEN u.value -> 'aliases' END
           AS aliases
FROM json_array_elements(%(rows)s::json) AS u(value)
"""

# The props merged with both, keys in order (D11), and without the ones that are null.
_ABBREVIATIONS_SQL = f"""
UPDATE instruments t
SET props = lg_unset(
    lg_update(t.props, json_build_object('short_title', r.short_title, 'aliases', r.aliases)),
    array_remove(ARRAY[
        CASE WHEN coalesce(json_typeof(r.short_title), 'null') = 'null'
             THEN 'short_title' END,
        CASE WHEN r.aliases IS NULL THEN 'aliases' END
    ], NULL)
)
FROM ({_ABBREVIATION_ROWS}) r
WHERE t.key = r.key
  AND ({differs_sql("t.props -> 'short_title'", "r.short_title")}
       OR {differs_sql("t.props -> 'aliases'", "r.aliases")})
RETURNING 1
"""


def update_abbreviations(store: Store, rows: list[dict[str, Any]]) -> int:
    """Set ``short_title`` and ``aliases`` on the instruments of *rows* (``{key,
    short_title, aliases}``) where either differs; how many changed. A null short title or
    an empty list of aliases removes the prop. A key twice in *rows* is written in rounds,
    in the order of *rows*."""
    changed = 0
    for round_ in _rounds(rows, "key"):
        changed += len(store.execute(_ABBREVIATIONS_SQL, {"rows": Json(round_)}))
    return changed


# The abbreviation of each instrument of *rows* (``{key, abbreviation}``), and the same as
# ``instrument_abbreviation`` on its articles (by ``bwb_id`` or ``celex``); a null one removes
# the prop. Only what differs is written; keys in order (D11).
_ABBREVIATION_SQL = f"""
WITH r AS (
    SELECT u.value ->> 'key' AS key, u.value -> 'abbreviation' AS abbreviation
    FROM json_array_elements(%(rows)s::json) AS u(value)
),
instruments_set AS (
    UPDATE instruments t
    SET props = CASE WHEN coalesce(json_typeof(r.abbreviation), 'null') = 'null'
                     THEN lg_unset(t.props, ARRAY['abbreviation'])
                     ELSE lg_update(t.props, json_build_object('abbreviation', r.abbreviation))
                END
    FROM r
    WHERE t.key = r.key AND {differs_sql("t.props -> 'abbreviation'", "r.abbreviation")}
    RETURNING 1
),
articles_set AS (
    UPDATE articles a
    SET props = CASE WHEN coalesce(json_typeof(r.abbreviation), 'null') = 'null'
                     THEN lg_unset(a.props, ARRAY['instrument_abbreviation'])
                     ELSE lg_update(
                         a.props, json_build_object('instrument_abbreviation', r.abbreviation)
                     )
                END
    FROM r JOIN instruments i ON i.key = r.key
    WHERE (a.bwb_id = i.bwb_id OR a.celex = i.celex)
      AND {differs_sql("a.props -> 'instrument_abbreviation'", "r.abbreviation")}
    RETURNING 1
)
SELECT (SELECT count(*) FROM instruments_set)::int + (SELECT count(*) FROM articles_set)::int
"""


def update_instrument_abbreviations(store: Store, rows: list[dict[str, Any]]) -> int:
    """Set ``abbreviation`` on the instruments of *rows* (``{key, abbreviation}``) and
    ``instrument_abbreviation`` on their articles where it differs; how many nodes changed.
    A null abbreviation removes both props."""
    return int(next(store.query(_ABBREVIATION_SQL, {"rows": Json(rows)}), 0))


_ARTICLES_SQL = """
SELECT key, props -> 'bwb_id' AS bwb_id, props -> 'stam_id' AS stam_id
FROM articles
WHERE bwb_id = ANY(%(ids)s)
ORDER BY key
"""


# ``text_start``: the first 60 characters of the text; "" without one (AQL's SUBSTRING of
# null).
_VERSIONS_SQL = """
SELECT key,
       props -> 'bwb_id' AS bwb_id,
       props -> 'stam_id' AS stam_id,
       props -> 'article_number' AS number,
       props -> 'label' AS label,
       props -> 'valid_from' AS valid_from,
       props -> 'valid_until' AS valid_until,
       props -> 'current' AS current,
       props -> 'last_seen' AS last_seen,
       props -> 'effect' AS effect,
       props -> 'content_digest' AS digest,
       props -> 'position' AS position,
       coalesce(left(props ->> 'text', 60), '') AS text_start,
       props -> 'instrument_citation_title' AS title
FROM article_versions
WHERE bwb_id = ANY(%(ids)s)
ORDER BY key
"""


def article_identities(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, stam_id}`` of the articles of *bwb_ids*."""
    return store.query(_ARTICLES_SQL, {"ids": bwb_ids})


def article_versions(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """The article versions of *bwb_ids*, with their validity and article number."""
    return store.query(_VERSIONS_SQL, {"ids": bwb_ids})


# The stored order: the versions with a position first, by it (a number before any other
# value, as ArangoDB sorts types), then those without; the key settles a tie.
_PLACES_SQL = """
SELECT key, props -> 'breadcrumb' AS breadcrumb,
       props -> 'breadcrumb_changes' AS breadcrumb_changes
FROM article_versions
WHERE bwb_id = %(id)s
ORDER BY coalesce(json_typeof(props -> 'position'), 'null') = 'null',
         lg_num(props -> 'position') NULLS LAST, key
"""


def stored_places(store: Store, bwb_id: str) -> Iterator[dict[str, Any]]:
    """``{key, breadcrumb, breadcrumb_changes}`` of the article versions of *bwb_id*, in
    their stored order (``position``)."""
    return store.query(_PLACES_SQL, {"id": bwb_id})


def article_version_starts(store: Store, keys: list[str]) -> dict[str, str]:
    """``valid_from`` of the article versions of *keys* that exist, by key."""
    rows = store.query(
        """
        SELECT key, props -> 'valid_from' AS valid_from FROM article_versions
        WHERE key = ANY(%(keys)s) AND json_typeof(props -> 'valid_from') <> 'null'
        ORDER BY key
        """,
        {"keys": keys},
    )
    return {row["key"]: row["valid_from"] for row in rows}


def toestand_starts(store: Store, bwb_ids: list[str]) -> dict[str, list[str]]:
    """The start dates of the toestanden of each of *bwb_ids*, oldest first."""
    rows = store.query(
        """
        SELECT bwb_id, array_agg(valid_from ORDER BY valid_from NULLS FIRST, key) AS starts
        FROM instrument_versions
        WHERE bwb_id = ANY(%(ids)s)
        GROUP BY bwb_id
        ORDER BY bwb_id
        """,
        {"ids": bwb_ids},
    )
    return {row["bwb_id"]: [s for s in row["starts"] if s] for row in rows}
