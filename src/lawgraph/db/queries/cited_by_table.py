"""``lg_cited_by``: every edge from a judgment into an article, with its passages and what
the citing judgment is sorted and counted on (``schema.article_cited_by``).

The triggers on ``edges`` and ``judgments`` keep it with every write; ``fill_cited_by`` adds
the edges written before them, a batch of judgments at a time (the edges of a judgment are
written together, so a batch reads few pages of the edges). The filters and facets of a
list of the judgments that cite an article (or any of several) are read from its rows.
"""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.db.schema import (
    CITED_BY_COLUMNS,
    CITED_BY_TABLE,
    cited_by_edges,
    cited_by_values,
)

# The filters of a list over its rows ``h`` (the columns ``tier``, ``areas`` and ``year``,
# the first four characters of ``date_eff``): any of ``%(tiers)s``, the year ``%(year)s``
# and the main area of law ``%(area)s``; each null for every value.
TIERS_KEPT = "(%(tiers)s::text[] IS NULL OR h.tier = ANY(%(tiers)s::text[]))"
YEAR_KEPT = "(%(year)s::text IS NULL OR h.year = %(year)s::text)"
AREA_KEPT = "(%(area)s::text IS NULL OR h.areas @> ARRAY[%(area)s::text])"


def court_kept(row: str) -> str:
    """SQL: the row *row* is of the court ``%(court)s`` (an ECLI court code; null: any)."""
    return f"(%(court)s::text IS NULL OR {row}.court_code = %(court)s::text)"


def _facet(
    value: str, rows: str, counted: str, where: str, order: str, many: bool
) -> str:
    """SQL: the judgments of *rows* (as ``h``) under *where*, counted per *value* (distinct
    *counted*), in *order*; with *many*, *value* is an array and a judgment counts for
    each of its values."""
    source = (
        f"{rows} h CROSS JOIN LATERAL unnest(h.{value}) AS u(value)"
        if many
        else f"{rows} h"
    )
    column = "u.value" if many else f"h.{value}"
    return f"""(
            SELECT coalesce(json_agg(json_build_object('value', f.value, 'count', f.n)
                                     ORDER BY {order}), '[]'::json)
            FROM (
                SELECT {column} AS value, count(DISTINCT h.{counted})::int AS n
                FROM {source} WHERE {where} GROUP BY {column}
            ) f
        )"""


def cited_by_facets(rows: str, counted: str) -> str:
    """SQL: a json object of the judgments of *rows* (as ``h``, before ``TIERS_KEPT``,
    ``YEAR_KEPT`` and ``AREA_KEPT``), each counted once by its column *counted*, each facet
    under the other filters: per ``year`` (oldest first, none first), per ``tier`` (most
    first) and per main area of law (``subject_area``, most first)."""
    return f"""json_build_object(
            'year', {
        _facet(
            "year",
            rows,
            counted,
            f"{TIERS_KEPT} AND {AREA_KEPT}",
            "f.value ASC NULLS FIRST",
            False,
        )
    },
            'tier', {
        _facet(
            "tier",
            rows,
            counted,
            f"{YEAR_KEPT} AND {AREA_KEPT}",
            "f.n DESC, f.value ASC",
            False,
        )
    },
            'subject_area', {
        _facet(
            "areas",
            rows,
            counted,
            f"{TIERS_KEPT} AND {YEAR_KEPT}",
            "f.n DESC, f.value ASC",
            True,
        )
    }
        )"""


# The judgments of one statement, with every edge from them into an article.
BATCH = 5_000

_FILL = f"""
WITH batch AS (
    SELECT j.id FROM judgments j
    WHERE j.id > %(after)s
    ORDER BY j.id
    LIMIT %(batch)s
),
kept AS (
    INSERT INTO {CITED_BY_TABLE} ({CITED_BY_COLUMNS})
    SELECT {cited_by_values("e", "j")}
    FROM batch b
    JOIN judgments j ON j.id = b.id
    JOIN edges e ON e.from_id = b.id AND {cited_by_edges("e")}
    WHERE %(every)s OR NOT EXISTS (SELECT 1 FROM {CITED_BY_TABLE} x WHERE x.edge_key = e.key)
    ON CONFLICT (edge_key) DO UPDATE SET
        article_id = EXCLUDED.article_id, judgment_id = EXCLUDED.judgment_id,
        mentions = EXCLUDED.mentions, leden = EXCLUDED.leden,
        date_eff = EXCLUDED.date_eff, ecli = EXCLUDED.ecli,
        court_code = EXCLUDED.court_code, tier = EXCLUDED.tier, cited = EXCLUDED.cited,
        areas = EXCLUDED.areas
    RETURNING 1
)
SELECT (SELECT max(id) FROM batch) AS last, (SELECT count(*) FROM kept)::int AS n
"""


def fill_cited_by(store: GraphStore, *, every: bool = False) -> int:
    """Keep every edge from a judgment into an article that the table lacks (with *every*:
    all of them again); the edges kept."""
    after, kept = "", 0
    while True:
        (row,) = store.execute(_FILL, {"after": after, "every": every, "batch": BATCH})
        if row["last"] is None:
            return kept
        after, kept = row["last"], kept + row["n"]
