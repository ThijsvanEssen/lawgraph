"""The list keys ``lawgraph semantic graph-list-stats`` keeps on nodes: per collection one
query that selects the documents whose stored keys differ from what the graph gives, and either
counts them (a dry run) or writes the keys. Each ``refresh_*`` returns the number.

What a key is read from decides what a run reads. The counts come from the edges, from an
index, of every node in every run: an edge that went lowers a count, and nothing tells which.
What only the props of a node give (the date of a judgment, the text of the articles of a
regulation) does not change while the row is not written again: with *written_after* (the
oldest transaction still open when the previous run began, ``pg_snapshot_xmin``) it is read of
the rows written since (``xmin``) and kept of the others; without, of every row."""

from __future__ import annotations

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
from lawgraph.core.courts import CODE_OTHER, COURT_BY_CODE, OTHER_COURT_BY_NAME, Court
from lawgraph.core.identifiers import (
    CELEX_PREPARATORY_SECTOR,
    EU_ACT_KINDS,
    KIND_PROPOSAL,
)
from lawgraph.core.judgment_kinds import KIND_OF_COURT_KIND
from lawgraph.core.judgment_names import CURATED_NAMES
from lawgraph.core.time import dutch_today
from lawgraph.db.counting import Store
from lawgraph.db.queries._chunks import update_props
from lawgraph.db.queries.instrument_scope import article_count, listed_article


def _differs(field: str, value: str, *, stored: bool) -> str:
    """``props.<field> != <value>``: a missing prop is null, ``1`` equals ``1.0``. With
    *stored*, the prop is read from its column ``pj_<field>``, not parsed out of the props."""
    prop = f"t.pj_{field}" if stored else f"(t.props -> '{field}')"
    return (
        f"coalesce({prop}::jsonb, 'null')"
        f" IS DISTINCT FROM coalesce(to_jsonb({value}), 'null')"
    )


def oldest_open_transaction(store: Store) -> int:
    """The oldest transaction still open (``pg_snapshot_xmin``, an ``xid8``): a row written
    by an older one was committed before now."""
    return int(
        next(
            store.query("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint")
        )
    )


def _written(alias: str) -> str:
    """SQL: the row *alias* was written by a transaction at or after ``%(written_after)s``
    (always, without one). A row frozen long ago can count as written (``age`` wraps): it is
    read again, no harm; the caller keeps the transactions in between far below the wrap."""
    return (
        "(%(written_after)s::xid IS NULL"
        f" OR age({alias}.xmin) BETWEEN 0 AND age(%(written_after)s::xid))"
    )


def _run(
    store: Store,
    table: str,
    computed: str,
    keys: list[str],
    bind: dict[str, Any],
    *,
    dry_run: bool,
    stored: bool = False,
) -> int:
    """Count the documents of *table* whose props differ from what *computed* gives (``id``
    and one column per key), or write the keys into them (``lg_update``). *stored*: the
    table keeps each key in a column ``pj_<key>`` (its props are large). The differing
    documents are read, then written in chunks: one statement over a whole table of
    judgments can run past ``LAWGRAPH_WRITE_TIMEOUT_MS``."""
    stale = f"""
        WITH computed AS ({computed}),
        stale AS (
            SELECT c.* FROM computed c JOIN {table} t USING (id)
            WHERE {" OR ".join(_differs(k, f"c.{k}", stored=stored) for k in keys)}
        )
    """
    if dry_run:
        return next(store.query(stale + "SELECT count(*)::int FROM stale", bind), 0)
    return update_props(
        store, table, store.query(stale + "SELECT * FROM stale", bind), keys
    )


# ``(props -> 'x')`` again for every field, never the whole props into a column: a judgment's
# props hold its text and paragraphs.
_INSTRUMENTS = f"""
    SELECT i.id,
           lower(coalesce(
               lg_str(i.props -> 'jurisdiction'),
               CASE WHEN i.celex IS NOT NULL THEN 'eu'
                    WHEN i.bwb_id IS NOT NULL THEN 'nl' END,
               ''
           )) AS jurisdiction,
           listed.articles AS article_count,
           -- an EU act by the letter of its CELEX number (no source names its kind), a
           -- preparatory act by its sector: a proposal
           coalesce(
               CASE WHEN i.bwb_id IS NOT NULL THEN NULL
                    WHEN i.celex ~ '^3[0-9]{{4}}[A-Z]'
                    THEN %(eu_kinds)s::jsonb ->> substr(i.celex, 6, 1)
                    WHEN left(i.celex, 1) = '{CELEX_PREPARATORY_SECTOR}'
                    THEN '{KIND_PROPOSAL}' END,
               lower(lg_str(i.props -> 'kind'))
           ) AS kind,
           -- what refers to the law: to the law itself, and to each of its articles and
           -- annexes (not to a treaty that belongs to it)
           (SELECT count(*)::int FROM edges e
            WHERE e.to_id = i.id AND e.relation = %(refers_to)s)
           + (SELECT count(*)::int FROM edges p
              JOIN edges e ON e.to_id = p.from_id AND e.relation = %(refers_to)s
              WHERE p.to_id = i.id AND p.relation = %(part_of)s
                AND p.from_collection <> 'instruments') AS inbound_citation_count,
           -- a BWB regulation that changes other regulations rather than standing on its
           -- own: articles numbered as a wijzigingsregeling (Artikel I, II, ...) of which one
           -- or more changes another regulation, or articles that mostly do. The BWB puts
           -- "Wijzigt <regulation>." in place of an article that did
           -- (``<redactie type="vervanging">``).
           CASE WHEN fresh.read
                THEN coalesce(i.bwb_id LIKE 'BWBR%%' AND text.changes > 0
                              AND (own.roman = own.articles
                                   OR 2 * text.changes >= own.articles),
                              false)
                ELSE coalesce(lg_bool(i.props -> 'amending'), false) END AS amending
    FROM instruments i
    -- what the list of its articles holds by default, counted once (OFFSET 0: not pulled
    -- up into each of the three places that read it)
    CROSS JOIN LATERAL (SELECT {article_count("i")} AS articles OFFSET 0) listed
    LEFT JOIN LATERAL (
        SELECT count(*) AS articles,
               count(*) FILTER (WHERE a.article_number ~ '^[IVXLC]+[a-z]?$') AS roman,
               count(*) FILTER (WHERE {_written("a")}) AS written
        FROM edges e JOIN articles a ON a.id = e.from_id
        WHERE e.to_id = i.id AND e.relation = %(part_of)s
          AND e.from_collection = 'articles'
          AND {" AND ".join(listed_article("a"))}
    ) own ON i.bwb_id LIKE 'BWBR%%'
    -- the texts of its articles are read of a regulation written since, one of whose
    -- articles was, or whose articles went (their count changed); the others keep theirs
    CROSS JOIN LATERAL (
        SELECT {_written("i")} OR coalesce(own.written, 0) > 0
               OR listed.articles IS DISTINCT FROM i.article_count AS read
    ) fresh
    LEFT JOIN LATERAL (
        SELECT count(*) FILTER (WHERE lg_str(a.props -> 'text') LIKE 'Wijzigt %%')
                   AS changes
        FROM edges e JOIN articles a ON a.id = e.from_id
        WHERE fresh.read AND e.to_id = i.id AND e.relation = %(part_of)s
          AND e.from_collection = 'articles'
          AND {" AND ".join(listed_article("a"))}
    ) text ON i.bwb_id LIKE 'BWBR%%'
"""


# The kind of an EU act by the letter of its CELEX number, in lower case as the BWB kinds:
# ``L`` ``richtlijn``.
EU_KINDS = {act.letter: act.noun.lower() for act in EU_ACT_KINDS.values()}


def refresh_instruments(
    store: Store, *, dry_run: bool, written_after: str | None = None
) -> int:
    return _run(
        store,
        "instruments",
        _INSTRUMENTS,
        ["jurisdiction", "article_count", "kind", "inbound_citation_count", "amending"],
        {
            "part_of": RELATION_PART_OF,
            "refers_to": RELATION_REFERS_TO,
            "eu_kinds": Jsonb(EU_KINDS),
            "written_after": written_after,
        },
        dry_run=dry_run,
    )


_JUDGMENTS = f"""
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
                       WHEN d.court_code = '{CODE_OTHER}'
                            AND %(other_court_by_name)s::jsonb
                                ? coalesce(nullif(d.court_name, ''), '')
                       THEN %(other_court_by_name)s::jsonb -> d.court_name
                       ELSE %(court_by_code)s::jsonb -> d.court_code
                   END AS court
            FROM (
                SELECT j.id, j.stub, j.court AS court_name, e.ecli,
                       CASE WHEN cardinality(string_to_array(e.ecli, ':')) >= 3
                            THEN upper(split_part(e.ecli, ':', 3)) END AS court_code,
                       -- of a judgment written since, from its props (its text too);
                       -- the others keep theirs
                       CASE WHEN {_written("j")} THEN coalesce(
                           j.props -> 'judgment_metadata' ->> 'date',
                           j.props -> 'meta' ->> 'date',
                           j.props ->> 'date'
                       ) ELSE j.date_eff END AS date_eff,
                       -- the judgments that cite it or a publication of the same decision
                       -- it keeps (SAME_AS to it), each once
                       -- (one ``= ANY`` of ids: an OR of the two keeps the index unused)
                       (SELECT count(DISTINCT e2.from_id)::int FROM edges e2
                        WHERE e2.relation = ANY(%(inbound_rels)s)
                          AND e2.from_collection = 'judgments'
                          AND e2.to_id = ANY(j.id || ARRAY(
                              SELECT s.from_id FROM edges s
                              WHERE s.to_id = j.id AND s.relation = %(same_as)s
                          ))) AS inbound_citation_count,
                       -- the judgments it cites
                       (SELECT count(*)::int FROM edges e3
                        WHERE e3.from_id = j.id AND e3.relation = ANY(%(inbound_rels)s)
                          AND e3.to_collection = 'judgments') AS outbound_citation_count,
                       lg_str(j.pj_decision_kind) AS stored_kind,
                       j.pj_names AS stored_names
                FROM judgments j,
                     LATERAL (SELECT coalesce(lg_str(j.pj_ecli), j.key) AS ecli) e
            ) d
        ) c
    ) j
"""


def _tiers(courts: dict[str, Court]) -> dict[str, dict[str, str]]:
    return {k: {"tier": c.tier, "court_kind": c.court_kind} for k, c in courts.items()}


def refresh_judgments(
    store: Store, *, dry_run: bool, written_after: str | None = None
) -> int:
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
            "written_after": written_after,
        },
        dry_run=dry_run,
        stored=True,
    )


_ARTICLES = """
    SELECT a.id,
           (SELECT count(*)::int FROM edges e
            WHERE e.to_id = a.id AND e.relation = ANY(%(inbound_rels)s))
               AS inbound_citation_count
    FROM articles a
"""


def refresh_articles(
    store: Store, *, dry_run: bool, written_after: str | None = None
) -> int:
    """(Every article: its key is a count; *written_after* changes nothing.)"""
    return _run(
        store,
        "articles",
        _ARTICLES,
        ["inbound_citation_count"],
        {"inbound_rels": [RELATION_REFERS_TO, RELATION_EXPLAINS]},
        dry_run=dry_run,
    )


# The open dossiers each committee leads, each once: those its activities are about and its
# cases are part of, as its page lists them (``lg_led``, ``queries/committees``); a dissolved
# committee leads none.
_COMMITTEES = """
    SELECT c.id,
           CASE WHEN lg_str(c.props -> 'ended_on') <= %(today)s THEN 0
                ELSE coalesce(led.n, 0) END AS active_dossier_count
    FROM committees c
    LEFT JOIN (
        SELECT l.to_id AS committee, count(DISTINCT a.to_id)::int AS n
        FROM edges l
        JOIN edges a ON a.from_id = l.from_id AND a.relation = ANY(%(in_dossier)s)
                    AND a.to_collection = 'dossiers'
        JOIN dossiers d ON d.id = a.to_id AND d.closed IS NOT TRUE
        WHERE l.relation = %(led_by)s AND l.to_collection = 'committees'
        GROUP BY l.to_id
    ) led ON led.committee = c.id
"""


def refresh_committees(
    store: Store, *, dry_run: bool, written_after: str | None = None
) -> int:
    """(Every committee: its key is a count; *written_after* changes nothing.)"""
    return _run(
        store,
        "committees",
        _COMMITTEES,
        ["active_dossier_count"],
        {
            "in_dossier": [RELATION_ABOUT, RELATION_PART_OF],
            "led_by": RELATION_LED_BY,
            "today": dutch_today().isoformat(),
        },
        dry_run=dry_run,
    )
