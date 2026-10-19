"""The terms of an article (``schema.ARTICLE_TERMS``): what the judgments that cite it call it.

Art. 41 Sr holds neither the word "noodweer" nor a heading, but the summaries of the
judgments that cite it do. A stem is a term of an article when it is in the light summaries
(``lg_judgment_light``, 400 characters each) of at least ``MIN_CITERS`` of its citing
judgments, ``MIN_LIFT`` times as often as in all summaries, and either in ``MIN_SHARE`` of
the summaries of its citers (what the article is about) or in ``MIN_SHARE`` of the summaries
that hold the stem those of its citers (what the word points to: "wanprestatie" is in a
twentieth of the summaries that cite art. 6:74 BW, cited on every subject, but a quarter of
the judgments that use the word cite it); ``TERMS`` at most, the most telling first. Each
with its strength (``strength``): how far the word names the article. Read from the light
summaries and the citing edges (``edges_to_cover``), never a judgment's text.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore

TERMS = 20
MIN_CITERS = 3
MIN_SHARE = 0.2
MIN_LIFT = 5.0
# A term names its article (``strength``) only when its citers hold it this many times as
# often as all summaries: "bestemmingsplan" is in a third of the summaries that cite art. 3:2
# Awb, and a third of those that hold it cite that article, but one in fifty judgments
# does, on every subject of the Raad van State (some 20 times as often).
NAME_LIFT = 50.0
# The strength of a term is the share it names its article by as low as it may be by chance:
# the lower bound of its Wilson interval at 95 % (``wilson_lower``).
WILSON_Z = 1.96
# The articles of one statement: their citing judgments and the stems of their summaries.
BATCH = 500
# The stem that holds how many light summaries there are (no stem is empty).
_ALL = ""

# Of every light summary its stems, each once: in how many summaries each is. One pass over
# ``lg_judgment_light``, kept in ``lg_summary_stems`` for the runs that follow a poll.
_COUNT_STEMS = """
SELECT t.stem, count(*)::int AS judgments
FROM lg_judgment_light l
CROSS JOIN LATERAL (
    SELECT DISTINCT s AS stem FROM unnest(lg_tokens(lg_str(l.props -> 'summary'))) AS s
) t
GROUP BY t.stem
HAVING count(*) >= %(min)s
UNION ALL
SELECT %(all)s, count(*)::int FROM lg_judgment_light
"""

# Per article its citing judgments, and per stem of their summaries in how many it is: only
# the stems in enough of them to be a term, of the citers or of the summaries that hold the
# stem (as the last whole run counted them, ``lg_summary_stems``; a stem new since then by
# its citers alone).
_ARTICLE_STEMS = f"""
WITH cites AS (
    SELECT DISTINCT a.id AS article_id, e.from_id AS judgment_id
    FROM unnest(%(ids)s::text[]) AS a(id)
    JOIN edges e ON e.to_id = a.id AND e.relation = '{RELATION_REFERS_TO}'
        AND e.from_collection = '{COLLECTION_JUDGMENTS}'
),
citers AS (
    SELECT article_id, count(*)::int AS n FROM cites GROUP BY article_id
),
stems AS (
    SELECT c.article_id, t.stem, count(*)::int AS n
    FROM cites c
    JOIN lg_judgment_light l ON l.id = c.judgment_id
    CROSS JOIN LATERAL (
        SELECT DISTINCT s AS stem FROM unnest(lg_tokens(lg_str(l.props -> 'summary'))) AS s
    ) t
    GROUP BY c.article_id, t.stem
)
SELECT s.article_id, s.stem, s.n, c.n AS citers
FROM stems s JOIN citers c ON c.article_id = s.article_id
LEFT JOIN lg_summary_stems w ON w.stem = s.stem
WHERE s.n >= %(min)s
  AND (s.n >= %(share)s * c.n OR s.n >= %(share)s * w.judgments)
ORDER BY s.article_id NULLS LAST, s.stem NULLS LAST
"""

_KEEP = """
WITH kept AS (
    SELECT * FROM unnest(%(ids)s::text[], %(terms)s::text[], %(strengths)s::text[])
        AS k(article_id, terms, strengths)
),
gone AS (
    DELETE FROM lg_article_terms t
    WHERE t.article_id = ANY(%(batch)s::text[])
      AND t.article_id <> ALL(%(ids)s::text[])
    RETURNING 1
),
written AS (
    INSERT INTO lg_article_terms (article_id, terms, strengths)
    SELECT k.article_id, string_to_array(k.terms, ' '),
           string_to_array(k.strengths, ' ')::real[]
    FROM kept k
    ON CONFLICT (article_id) DO UPDATE
    SET terms = EXCLUDED.terms, strengths = EXCLUDED.strengths
    WHERE (lg_article_terms.terms, lg_article_terms.strengths)
        IS DISTINCT FROM (EXCLUDED.terms, EXCLUDED.strengths)
    RETURNING 1
)
SELECT (SELECT count(*) FROM gone)::int + (SELECT count(*) FROM written)::int AS changed
"""


@dataclass(frozen=True)
class SummaryStems:
    """In how many light summaries each stem is, of how many."""

    judgments: int
    stems: dict[str, int]


def count_summary_stems(store: GraphStore) -> SummaryStems:
    """Count the stems of every light summary, and keep the counts for the runs after."""
    counts = {
        row["stem"]: row["judgments"]
        for row in store.query(_COUNT_STEMS, {"min": MIN_CITERS, "all": _ALL})
    }
    store.execute_together(
        [
            ("TRUNCATE lg_summary_stems", None),
            (
                "INSERT INTO lg_summary_stems (stem, judgments)"
                " SELECT * FROM unnest(%(stems)s::text[], %(counts)s::int[])",
                {"stems": list(counts), "counts": list(counts.values())},
            ),
        ]
    )
    total = counts.pop(_ALL, 0)
    return SummaryStems(total, counts)


def kept_summary_stems(store: GraphStore, stems: Iterable[str]) -> SummaryStems:
    """The counts the last whole run kept, of *stems*."""
    wanted = sorted({*stems, _ALL})
    counts = {
        row["stem"]: row["judgments"]
        for row in store.query(
            "SELECT stem, judgments FROM lg_summary_stems WHERE stem = ANY(%(stems)s)",
            {"stems": wanted},
        )
    }
    return SummaryStems(counts.pop(_ALL, 0), counts)


def cited_articles(store: GraphStore) -> list[str]:
    """Every article that enough judgments cite to have terms, in id order."""
    return list(
        store.query(
            f"SELECT id FROM {COLLECTION_ARTICLES}"
            " WHERE inbound_citation_count >= %(min)s ORDER BY id",
            {"min": MIN_CITERS},
        )
    )


def articles_cited_since(store: GraphStore, moment: str) -> list[str]:
    """The articles a judgment cited in an edge written at or after *moment*."""
    return list(
        store.query(
            f"""
            SELECT DISTINCT e.to_id FROM edges e
            WHERE e.created_at >= %(moment)s AND e.relation = '{RELATION_REFERS_TO}'
              AND e.from_collection = '{COLLECTION_JUDGMENTS}'
              AND e.to_collection = '{COLLECTION_ARTICLES}'
            ORDER BY e.to_id
            """,
            {"moment": moment},
        )
    )


def _lift(n: int, citers: int, stem: str, counts: SummaryStems) -> float:
    """How many times as often *stem* is in the summaries of the citers as in all. A stem
    the counts lack (in fewer summaries than a term needs at the last whole run) is in at
    least the *n* of the citers."""
    if not counts.judgments:
        return math.inf
    everywhere = max(counts.stems.get(stem, 0), n)
    return (n / citers) / (everywhere / counts.judgments)


def strength(n: int, lift: float, stem: str, counts: SummaryStems) -> float:
    """How far *stem* names the article whose *n* citers hold it: the share of the summaries
    holding it that cite the article, as low as it may be by chance (``wilson_lower``): 29
    of 128 for "verjaring" and art. 3:310 BW, 0.16; 3 of 9 for "concurrentiebeding" and art.
    6:97 BW, a third, but 0.12. 0 for a word its citers hold under ``NAME_LIFT`` times as
    often as all summaries (or before a whole run counted them)."""
    if lift < NAME_LIFT or not counts.judgments:
        return 0.0
    return round(wilson_lower(n, max(counts.stems.get(stem, 0), n)), 3)


def wilson_lower(n: int, of: int) -> float:
    """The lower bound of the Wilson score interval (95 %) of the share *n* of *of*: a share
    of few counts is little evidence, and weighs less than the same share of many."""
    z2 = WILSON_Z * WILSON_Z
    share = n / of
    spread = WILSON_Z * math.sqrt(share * (1 - share) / of + z2 / (4 * of * of))
    return (share + z2 / (2 * of) - spread) / (1 + z2 / of)


def terms_of(
    rows: Iterable[dict[str, object]], counts: SummaryStems
) -> dict[str, list[tuple[str, float]]]:
    """Per article its terms with their strength, the most telling first (in more citers,
    and more lifted)."""
    scored: dict[str, list[tuple[float, str, float]]] = {}
    for row in rows:
        stem = str(row["stem"])
        if len(stem) < 3 or stem.isdigit():
            continue
        n, citers = int(row["n"]), int(row["citers"])  # type: ignore[call-overload]
        lift = _lift(n, citers, stem, counts)
        if lift < MIN_LIFT:
            continue
        weight = n * math.log(min(lift, 1e6))
        scored.setdefault(str(row["article_id"]), []).append(
            (-weight, stem, strength(n, lift, stem, counts))
        )
    return {
        article: [(stem, named) for _, stem, named in sorted(found)[:TERMS]]
        for article, found in scored.items()
    }


def raise_articles_version(store: GraphStore) -> None:
    """Raise the data version of ``articles``: the search finds an article by its terms,
    and keeps its answers per version of the articles."""
    store.execute(
        "UPDATE lg_data_version SET version = version + 1 WHERE collection = %(c)s",
        {"c": COLLECTION_ARTICLES},
    )


def keep_terms(
    store: GraphStore, articles: list[str], counts: SummaryStems | None = None
) -> int:
    """Keep the terms of *articles*, a batch at a time; the articles whose terms changed.

    Without *counts* those the last whole run kept (``lg_summary_stems``)."""
    changed = 0
    for start in range(0, len(articles), BATCH):
        batch = articles[start : start + BATCH]
        rows = list(
            store.query(
                _ARTICLE_STEMS, {"ids": batch, "min": MIN_CITERS, "share": MIN_SHARE}
            )
        )
        known = counts or kept_summary_stems(store, (str(r["stem"]) for r in rows))
        found = terms_of(rows, known)
        # (one column: the store gives its value)
        (written,) = store.execute(
            _KEEP,
            {
                "batch": batch,
                "ids": list(found),
                "terms": [" ".join(t for t, _ in terms) for terms in found.values()],
                "strengths": [
                    " ".join(str(s) for _, s in terms) for terms in found.values()
                ],
            },
        )
        changed += written
    return changed
