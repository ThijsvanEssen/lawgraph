"""The list keys ``lawgraph semantic graph-list-stats`` keeps on nodes: per collection one
query that selects the documents whose stored keys differ from what the graph gives, and either
counts them (a dry run) or writes the keys. Each ``refresh_*`` returns the number."""

from __future__ import annotations

import datetime as dt
from typing import Any

from psycopg.types.json import Jsonb

from lawgraph.config.constants import (
    RELATION_ABOUT,
    RELATION_EXPLAINS,
    RELATION_LED_BY,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_SAME_AS,
)
from lawgraph.core.courts import COURT_BY_CODE, OTHER_COURT_BY_NAME, Court
from lawgraph.core.judgment_names import CURATED_NAMES
from lawgraph.core.judgments import KIND_OF_COURT_KIND
from lawgraph.db.counting import Store


def _differs(field: str, value: str) -> str:
    """``doc.props.<field> != <value>``: a missing prop is null, ``1`` equals ``1.0``."""
    return (
        f"coalesce((props -> '{field}')::jsonb, 'null')"
        f" IS DISTINCT FROM coalesce(to_jsonb({value}), 'null')"
    )


def _run(
    store: Store,
    table: str,
    computed: str,
    keys: list[str],
    bind: dict[str, Any],
    *,
    dry_run: bool,
) -> int:
    """Count the documents of *table* whose props differ from what *computed* gives (``id``
    and one column per key), or write the keys into them (``lg_update``, D11)."""
    stale = f"""
        WITH computed AS ({computed}),
        stale AS (
            SELECT c.* FROM computed c JOIN {table} t USING (id)
            WHERE {" OR ".join(_differs(k, f"c.{k}") for k in keys)}
        )
    """
    if dry_run:
        return next(store.query(stale + "SELECT count(*)::int FROM stale", bind), 0)
    pairs = ", ".join(f"'{k}', s.{k}" for k in keys)
    rows = store.execute(
        stale
        + f"""
        UPDATE {table} t SET props = lg_update(t.props, json_build_object({pairs}))
        FROM stale s WHERE t.id = s.id
        RETURNING 1
        """,
        bind,
    )
    return len(rows)


# ``(props -> 'x')`` again for every field, never the whole props into a column: a judgment's
# props hold its text and paragraphs.
_INSTRUMENTS = """
    SELECT i.id,
           lower(coalesce(
               lg_str(i.props -> 'jurisdiction'),
               CASE WHEN i.celex IS NOT NULL THEN 'eu'
                    WHEN i.bwb_id IS NOT NULL THEN 'nl' END,
               ''
           )) AS jurisdiction,
           -- its articles only: its annexes are PART_OF it too
           (SELECT count(*)::int FROM edges e
            WHERE e.to_id = i.id AND e.relation = %(part_of)s
              AND e.from_collection = 'articles') AS article_count,
           lower(lg_str(i.props -> 'kind')) AS kind,
           -- what refers to the law: to the law itself, and to each of its articles
           (SELECT count(*)::int FROM edges e
            WHERE e.to_id = i.id AND e.relation = %(refers_to)s)
           + (SELECT count(*)::int FROM edges p
              JOIN edges e ON e.to_id = p.from_id AND e.relation = %(refers_to)s
              WHERE p.to_id = i.id AND p.relation = %(part_of)s) AS inbound_citation_count
    FROM instruments i
"""


def refresh_instruments(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        "instruments",
        _INSTRUMENTS,
        ["jurisdiction", "article_count", "kind", "inbound_citation_count"],
        {"part_of": RELATION_PART_OF, "refers_to": RELATION_REFERS_TO},
        dry_run=dry_run,
    )


_JUDGMENTS = """
    SELECT j.id, j.court_code, j.tier, j.court_kind, j.date_eff,
           j.inbound_citation_count, j.outbound_citation_count,
           coalesce(j.stored_kind, %(kind_of_court_kind)s::jsonb ->> j.court_kind) AS decision_kind,
           CASE WHEN j.stub IS TRUE THEN (%(curated_names)s::jsonb -> upper(j.ecli))::json
                ELSE j.stored_names END AS names
    FROM (
        SELECT c.*,
               court ->> 'tier' AS tier,
               court ->> 'court_kind' AS court_kind
        FROM (
            SELECT d.*,
                   CASE
                       WHEN d.court_code IS NULL THEN NULL
                       WHEN d.court_code = 'XX'
                            AND %(other_court_by_name)s::jsonb
                                ? coalesce(nullif(lg_str(d.props -> 'court'), ''), '')
                       THEN %(other_court_by_name)s::jsonb -> lg_str(d.props -> 'court')
                       ELSE %(court_by_code)s::jsonb -> d.court_code
                   END AS court
            FROM (
                SELECT j.id, j.props, j.stub, e.ecli,
                       CASE WHEN cardinality(string_to_array(e.ecli, ':')) >= 3
                            THEN upper(split_part(e.ecli, ':', 3)) END AS court_code,
                       coalesce(
                           j.props -> 'judgment_metadata' ->> 'date',
                           j.props -> 'meta' ->> 'date',
                           j.props ->> 'date'
                       ) AS date_eff,
                       -- the judgments that cite it or a publication of the same decision
                       -- it keeps (SAME_AS to it), each once
                       (SELECT count(DISTINCT e2.from_id)::int FROM edges e2
                        WHERE e2.relation = ANY(%(inbound_rels)s)
                          AND e2.from_collection = 'judgments'
                          AND (e2.to_id = j.id OR e2.to_id IN (
                              SELECT s.from_id FROM edges s
                              WHERE s.to_id = j.id AND s.relation = %(same_as)s
                          ))) AS inbound_citation_count,
                       -- the judgments it cites
                       (SELECT count(*)::int FROM edges e3
                        WHERE e3.from_id = j.id AND e3.relation = ANY(%(inbound_rels)s)
                          AND e3.to_collection = 'judgments') AS outbound_citation_count,
                       lg_str(j.props -> 'decision_kind') AS stored_kind,
                       j.props -> 'names' AS stored_names
                FROM judgments j,
                     LATERAL (SELECT coalesce(lg_str(j.props -> 'ecli'), j.key) AS ecli) e
            ) d
        ) c
    ) j
"""


def _tiers(courts: dict[str, Court]) -> dict[str, dict[str, str]]:
    return {k: {"tier": c.tier, "court_kind": c.court_kind} for k, c in courts.items()}


def refresh_judgments(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        "judgments",
        _JUDGMENTS,
        [
            "court_code",
            "tier",
            "court_kind",
            "date_eff",
            "inbound_citation_count",
            "outbound_citation_count",
            "decision_kind",
            "names",
        ],
        {
            "inbound_rels": [RELATION_REFERS_TO],
            "same_as": RELATION_SAME_AS,
            "court_by_code": Jsonb(_tiers(COURT_BY_CODE)),
            "other_court_by_name": Jsonb(_tiers(OTHER_COURT_BY_NAME)),
            "kind_of_court_kind": Jsonb(KIND_OF_COURT_KIND),
            "curated_names": Jsonb({e: list(n) for e, n in CURATED_NAMES.items()}),
        },
        dry_run=dry_run,
    )


_ARTICLES = """
    SELECT a.id,
           (SELECT count(*)::int FROM edges e
            WHERE e.to_id = a.id AND e.relation = ANY(%(inbound_rels)s))
               AS inbound_citation_count
    FROM articles a
"""


def refresh_articles(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        "articles",
        _ARTICLES,
        ["inbound_citation_count"],
        {"inbound_rels": [RELATION_REFERS_TO, RELATION_EXPLAINS]},
        dry_run=dry_run,
    )


# The open dossiers each committee leads an activity about, each once; a dissolved
# committee leads none.
_COMMITTEES = """
    SELECT c.id,
           CASE WHEN lg_str(c.props -> 'ended_on') <= %(today)s THEN 0
                ELSE coalesce(led.n, 0) END AS active_dossier_count
    FROM committees c
    LEFT JOIN (
        SELECT l.to_id AS committee, count(DISTINCT a.to_id)::int AS n
        FROM edges l
        JOIN edges a ON a.from_id = l.from_id AND a.relation = %(about)s
        JOIN dossiers d ON d.id = a.to_id AND d.closed IS NOT TRUE
        WHERE l.relation = %(led_by)s
        GROUP BY l.to_id
    ) led ON led.committee = c.id
"""


def refresh_committees(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        "committees",
        _COMMITTEES,
        ["active_dossier_count"],
        {
            "about": RELATION_ABOUT,
            "led_by": RELATION_LED_BY,
            "today": dt.date.today().isoformat(),
        },
        dry_run=dry_run,
    )
