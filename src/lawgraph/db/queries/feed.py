"""The query behind the news feed (``GET /api/feed``): the dated events of the graph, newest
first, in one SQL statement.

The light rows of every kind (``feed_sql``) are put together, sorted by date (descending),
the rank of the kind and id, and cut after the cursor; only the rows of the page are then
read in full (``_items``). With ``facets`` the total, the facets and the page are made from
one read of every row under the filters. The summary of the homepage reads the same rows.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import replace
from typing import Any, cast

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core.dossier_stages import LEGISLATIVE_KINDS
from lawgraph.core.ecli import ECLI_EU_PREFIX
from lawgraph.core.feed import (
    DEFAULT_KINDS,
    EVENT_BILL,
    EVENT_COMMENCEMENT,
    EVENT_COMMITMENT,
    EVENT_JUDGMENT,
    EVENT_PUBLICATION,
    EVENT_VOTE,
    FEED_KINDS,
    FeedCursor,
)
from lawgraph.core.judgment_kinds import KIND_CONCLUSIE
from lawgraph.core.time import day_before, dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import feed_events
from lawgraph.db.queries._helpers import page_with_counts, with_counts
from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    as_text,
    is_present,
    truthy_or,
)
from lawgraph.db.queries._lists import FACET_AGG, FacetFilters, facet
from lawgraph.db.queries.coalition_sql import coalition_factions, coalition_object
from lawgraph.db.queries.feed_relations import (
    CITATIONS_OF_LAW,
    COMMENCED,
    ENACTED,
    ENACTED_OF_REGULATION,
    PUBLICATION_IDENTIFIER,
    RELATIONS,
    via,
)
from lawgraph.db.queries.feed_sql import (
    ACTORS,
    BWB_KEY,
    CITATION_TITLE,
    COMMITMENT_PERSONS,
    DECIDED_PERSONS,
    DIMENSIONS,
    JSON_TEXT,
    LAW_KEY,
    SOURCES,
    FeedFilters,
    Plan,
    bill_persons,
    cabinet_on,
    dimension_facet,
    dimension_filters,
    kinds_of,
    law_edges,
    lit,
    of_kind,
    party_choice,
    per_coalition,
    per_faction,
    rows_of,
    shared_filters,
)
from lawgraph.db.queries.judgment_light import OUTCOME_KEYS
from lawgraph.db.schema import (
    FEED_EVENTS_TABLE,
)
from lawgraph.db.store import read_budget, read_time_left
from lawgraph.db.version_cache import cached, lasting

# The instruments a publication names at most.
MAX_CHANGED_INSTRUMENTS = 10
# The props of the page's nodes the items show; never the text of a document.
_ITEM_PROPS = (
    "kind",
    "title",
    "subject",
    "display_name",
    "document_number",
    "sequence",
    # with ``sequence``, what the readable address of a document or a commitment is made of
    # (``core.readable_paths.path_of``): its own dossier, and the letter of an Eerste Kamer
    # document or the number of a commitment
    "dossier_number",
    "dossier_suffix",
    "number",
    "status",
    "expected_resolution",
    "minister_name",
    "decision_text",
    "passed",
    "tally",
    "vote_kind",
    "method",
    "decision_kind",
    "chamber",
    # of a motion of censure or of no confidence, and of a vote on one (``core/motion_kinds``)
    "motion_kind",
    "citation_title",
    "publication_kind",
    "publication_year",
    "publication_number",
    "bwb_id",
    "valid_from",
    "ecli",
    "court_code",
    "tier",
    "court_kind",
    "procedure",
    "date_eff",
    "published_on",
    "summary",
    "advocate_general",
    "advocate_general_role",
    "case_number",
    # how a judgment ended, what a conclusion proposes, what the ECHR found
    # (``queries/judgment_light.OUTCOME_KEYS``)
    *OUTCOME_KEYS,
    "source",
)
# The name a bill gives itself: "Deze wet wordt aangehaald als: Wet sterkere archieven.",
# up to the full stop or the end of its line, without the spaces around it.
_CITED = r"wordt aangehaald als:?\s*([^.\s][^.\n]{1,148}[^.\s])"

# The order of the feed: newest day first, within a day by the rank of the kind
# (``core.feed.DAY_ORDER``), then by id.
_ORDER = "date DESC NULLS LAST, rank ASC, id ASC"
_PAGE_ORDER = "pg.date DESC NULLS LAST, pg.rank ASC, pg.id ASC"

_OWN_ACTORS = "props -> 'actors'"

# The props of a judgment an item shows, from its columns: its own props hold its text and
# paragraphs, which a read of one prop would parse; the A-G of a conclusion alone, the case
# number of a judgment of a court of the Union alone (its ``cite`` names it).
_JUDGMENT_PROPS = f"""json_build_object(
                'display_name', pj_display_name, 'ecli', pj_ecli,
                'court_code', pj_court_code, 'tier', pj_tier,
                'court_kind', pj_court_kind, 'decision_kind', pj_decision_kind,
                'procedure', to_json(procedure), 'date_eff', pj_date_eff,
                'published_on', to_json(published_on), 'summary', pj_summary,
                'source', pj_source,
                'advocate_general', CASE WHEN pj_decision_kind {JSON_TEXT} = {lit(KIND_CONCLUSIE)}
                    THEN props -> 'advocate_general' END,
                'advocate_general_role', CASE WHEN pj_decision_kind {JSON_TEXT} = {lit(KIND_CONCLUSIE)}
                    THEN props -> 'advocate_general_role' END,
                'case_number', CASE WHEN starts_with(pj_ecli {JSON_TEXT}, {lit(ECLI_EU_PREFIX)})
                    THEN props -> 'case_number' END
            )"""


def _node_of(row: str) -> str:
    """SQL: ``n``, the node (``id``, ``props``, ``pj_actors``) of the page row *row*."""
    tables = sorted({s.collection for s in SOURCES.values()})
    props = {COLLECTION_JUDGMENTS: _JUDGMENT_PROPS}
    # a document's signatures from their column; a judgment has none
    actors = {COLLECTION_DOCUMENTS: "pj_actors", COLLECTION_JUDGMENTS: "NULL::json"}
    union = "\n            UNION ALL ".join(
        f"SELECT id, {props.get(table, 'props')} AS props, "
        f"{actors.get(table, _OWN_ACTORS)} AS pj_actors"
        f" FROM {table} WHERE id = {row}.id"
        for table in tables
    )
    return f"""CROSS JOIN LATERAL (
            {union}
        ) n"""


_DOCUMENT_TEXT = (
    "CASE WHEN lg_truthy(paper.props -> 'text') THEN paper.props ->> 'text' ELSE '' END"
)
# ``case_ids OR []`` and ``signatures OR []`` walked: a value that is no array as ``[]``.
_CASE_IDS = array_or_empty("paper.props -> 'case_ids'")


def _official_short(label: str) -> str:
    """SQL: the name the bill of the dossier labelled *label* goes by, from official data
    only: the citation title its own text gives ("Deze wet wordt aangehaald als: …"), the
    citation title the Kamer gives its case, or the citation title of the one Dutch law it
    changes; ``{title, basis}`` with ``basis`` ``citation``, ``case`` or ``amended_law``,
    null when none of them is there."""
    return f"""(
            SELECT CASE
                WHEN os.cited IS NOT NULL THEN json_build_object(
                    'title', os.cited, 'basis', 'citation'::text)
                WHEN os.case_title IS NOT NULL THEN json_build_object(
                    'title', os.case_title, 'basis', 'case'::text)
                WHEN {is_present("law.props -> 'bwb_id'")}
                     AND {is_present("law.props -> 'citation_title'")}
                    THEN json_build_object(
                        'title', law.props -> 'citation_title',
                        'basis', 'amended_law'::text)
            END
            FROM (
                SELECT paper.id, paper.props FROM {COLLECTION_DOCUMENTS} paper
                WHERE {label} IS NOT NULL AND paper.dossier_numbers @> ARRAY[{label}]
                  AND {of_kind("paper.kind", EVENT_BILL)}
                ORDER BY paper.date ASC NULLS FIRST, paper.key ASC
                LIMIT 1
            ) paper
            CROSS JOIN LATERAL (
                SELECT
                    (regexp_match({_DOCUMENT_TEXT}, %(cited)s, 'i'))[1] AS cited,
                    (SELECT c.props -> 'citation_title'
                     FROM json_array_elements({_CASE_IDS})
                         WITH ORDINALITY AS ids(case_id, ord)
                     JOIN {COLLECTION_CASES} c ON c.id = {lit(COLLECTION_CASES + "/")}
                         || lg_node_key(ids.case_id {JSON_TEXT})
                     WHERE {is_present("c.props -> 'citation_title'")}
                     ORDER BY ids.ord
                     LIMIT 1) AS case_title,
                    ARRAY(
                        SELECT DISTINCT {LAW_KEY}
                        {law_edges("paper.id")}
                    ) AS laws
                OFFSET 0
            ) os
            LEFT JOIN {COLLECTION_INSTRUMENTS} law
                ON cardinality(os.laws) = 1 AND law.key = os.laws[1]
        )"""


def official_short(store: GraphStore, label: str) -> dict[str, Any] | None:
    """The name the bill of the dossier labelled *label* goes by in official data
    (``_official_short``): ``{title, basis}``, None without."""
    # the one column of the one row: its value
    (found,) = store.query(
        f"SELECT {_official_short('%(label)s::text')}",
        {"label": label, "cited": _CITED},
    )
    return found if isinstance(found, dict) else None


# The signatures of an event on the page, by its kind.
_SIGNATURES = f"""CASE pg.kind
                WHEN {lit(EVENT_COMMITMENT)} THEN {COMMITMENT_PERSONS}
                WHEN {lit(EVENT_VOTE)} THEN {DECIDED_PERSONS}
                WHEN {lit(EVENT_BILL)} THEN {bill_persons("pg.dossier")}
                ELSE {ACTORS} END"""

# A signature as an item shows it: with the key, name and slug of its member (a member's
# key is its TK GUID made a node key) and its faction, set over what the signature has
# (``lg_update``).
# The key of the member of a signature's TK GUID: the GUID in lower case with ``_`` for
# ``-`` (what ``lg_node_key`` makes of a GUID; in its place the planner turns the join of
# the page).
_PERSON_KEY = "replace(lower(s.p ->> 'person_id'), '-', '_')"
# The member's name is the expression of ``members.list_name`` on its props: read as the
# column, the planner turns the join of the page.
_MEMBER_NAME = truthy_or(
    truthy_or("m.props -> 'name'", "m.props -> 'known_as'"),
    "m.props -> 'government_name'",
)
_PERSONS = f"""CROSS JOIN LATERAL (
            SELECT coalesce(json_agg(
                CASE WHEN json_typeof(s.p) = 'object' THEN lg_update(s.p, json_build_object(
                    'faction', (SELECT json_build_object('key', fo.key, 'short', fo.short)
                                FROM faction_of fo
                                WHERE fo.fid = lg_str(s.p -> 'faction_id')),
                    'member_name', {_MEMBER_NAME},
                    'member_key', who.key,
                    'member_slug', m.props -> 'slug'
                )) END
                ORDER BY s.o), {EMPTY_ARRAY}) AS value
            FROM json_array_elements({array_or_empty("sig.value")})
                WITH ORDINALITY AS s(p, o)
            CROSS JOIN LATERAL (SELECT CASE
                WHEN lg_truthy(s.p -> 'member_key') THEN s.p -> 'member_key'
                WHEN {is_present("s.p -> 'person_id'")}
                    THEN to_json({_PERSON_KEY})
            END AS key) who
            LEFT JOIN LATERAL (
                SELECT props FROM {COLLECTION_MEMBERS} WHERE key = (who.key {JSON_TEXT})
            ) m ON true
        ) persons"""

_CHANGED_TITLE = truthy_or("c.props -> 'citation_title'", "c.props -> 'title'")
# The laws a publication enacts (``establishes``: the regulations that name it as the one
# that enacted them, with their articles) and those it changes, each once: ``amends``,
# ``introduces`` or ``repeals`` where every change it makes in the law is of that one kind,
# else ``amends``, with the articles it touches; the laws it enacts first, then by title.
_CHANGED_INSTRUMENTS = f"""CASE WHEN pg.kind = {lit(EVENT_PUBLICATION)} THEN (
                SELECT coalesce(json_agg(json_build_object(
                    'key', c.key,
                    'title', {_CHANGED_TITLE},
                    'bwb_id', c.props -> 'bwb_id',
                    'effect', c.effect,
                    'article_count', c.articles
                ) ORDER BY c.rank, c.citation_title ASC NULLS FIRST, c.key ASC), {EMPTY_ARRAY})
                FROM (
                    SELECT c.*
                    FROM (
                        SELECT DISTINCT ON (i.key) i.key, i.props, i.citation_title,
                               changed.effect, changed.articles, changed.rank
                        FROM (
                            SELECT r.key, 'establishes' AS effect,
                                   r.article_count::int AS articles, 0 AS rank
                            FROM {COLLECTION_INSTRUMENTS} r
                            WHERE {ENACTED} = {PUBLICATION_IDENTIFIER}
                              AND {ENACTED_OF_REGULATION}
                            UNION ALL
                            SELECT law.key,
                                   CASE WHEN count(DISTINCT law.relation) = 1
                                        THEN lower(min(law.relation)) ELSE 'amends' END,
                                   count(DISTINCT law.article)::int, 1
                            FROM (
                                SELECT {LAW_KEY} AS key, e.relation,
                                       CASE WHEN e.to_collection = {lit(COLLECTION_ARTICLES)}
                                            THEN e.to_id END AS article
                                {law_edges("pg.id")}
                            ) law
                            GROUP BY law.key
                        ) changed
                        JOIN {COLLECTION_INSTRUMENTS} i ON i.key = changed.key
                        ORDER BY i.key, changed.rank
                    ) c
                    ORDER BY c.rank, c.citation_title ASC NULLS FIRST, c.key ASC
                    LIMIT {MAX_CHANGED_INSTRUMENTS}
                ) c
            ) ELSE {EMPTY_ARRAY} END"""

_CHANGED_ARTICLES = f"""CASE WHEN pg.kind = {lit(EVENT_COMMENCEMENT)} THEN (
                SELECT count(*)::int FROM {COLLECTION_ARTICLE_VERSIONS} v
                WHERE lg_str(n.props -> 'bwb_id') IS NOT NULL
                  AND v.bwb_id = lg_str(n.props -> 'bwb_id')
                  AND v.valid_from = lg_str(n.props -> 'valid_from')
            ) ELSE 0 END"""

# The title of an item ``pg`` the words of ``q`` are matched in, as its kind's ``Source.title``
# (on the full node ``n`` of the page), in lower case.
_MATCHED_TITLE = f"""lower(CASE pg.kind
                WHEN {lit(EVENT_COMMITMENT)} THEN n.props ->> 'text'
                WHEN {lit(EVENT_VOTE)} THEN n.props ->> 'subject'
                WHEN {lit(EVENT_PUBLICATION)} THEN n.props ->> 'citation_title'
                WHEN {lit(EVENT_JUDGMENT)} THEN n.props ->> 'display_name'
                WHEN {lit(EVENT_COMMENCEMENT)} THEN instrument.value ->> 'title'
                ELSE {as_text(truthy_or("n.props -> 'subject'", "n.props -> 'title'"))} END)"""
# Per word of ``q`` that an item holds, where it holds it (``{term, field}``): its ``title``,
# else the ``dossier_title`` of its first dossier, else the names of its ``laws`` (of a
# publication, as ``lawgraph feed-events`` wrote them with its title); read for the items
# of the page alone.
_MATCHED = f"""(
                SELECT coalesce(json_agg(json_build_object('term', w.term, 'field', w.field)
                                         ORDER BY w.n), {EMPTY_ARRAY})
                FROM (
                    SELECT w.n, w.term, CASE
                        WHEN {_MATCHED_TITLE} ~ w.pattern THEN 'title'
                        WHEN lower(dossier.value ->> 'title') ~ w.pattern THEN 'dossier_title'
                        WHEN pg.kind = {lit(EVENT_PUBLICATION)} AND (
                            SELECT e.title FROM {FEED_EVENTS_TABLE} e
                            WHERE e.kind = pg.kind AND e.id = pg.id) ~ w.pattern THEN 'laws'
                    END AS field
                    FROM unnest(%(q_terms)s::text[], %(q_patterns)s::text[])
                        WITH ORDINALITY AS w(term, pattern, n)
                ) w
                WHERE w.field IS NOT NULL
            )"""

_RELATIONS = ",\n            ".join(f"{lit(name)}, {sql}" for name, sql in RELATIONS)


# The page (``page``), read in full: the node's props, its first dossier, the cabinet on its
# date, the signatures with their factions, of a document whether it has its text and its
# dictum (``lg_document_light``), of a vote what the coalition did, and what a kind adds (who
# made a commitment, the laws a publication enacts or changes, the law, the articles and the
# publication of a new version and what it is issued under), the sources it is tied to
# (``feed_relations.RELATIONS``), where it holds the words of ``q`` (``matched``) and how it
# is tied to the law followed (``via``).
def _items(filters: FeedFilters) -> str:
    """SQL: the items of the page (``page``) under *filters*: with ``matched`` of each item
    under words and ``via`` when they follow a law."""
    via_law = via(article=bool(filters.article)) if filters.instrument else "NULL::json"
    matched = _MATCHED if filters.q else "NULL::json"
    voted = party_choice("pg.id") if filters.party else "NULL::text"
    return f"""(
        SELECT coalesce(json_agg(json_build_object(
            'kind', pg.kind,
            'id', pg.id,
            'date', pg.date,
            'ministry', pg.ministry,
            'cabinet', {cabinet_on("pg.date")},
            'dossier', dossier.value,
            'props', (
                SELECT coalesce(json_object_agg(k.key, k.value), '{{}}'::json)
                FROM json_each(n.props) AS k(key, value)
                WHERE k.key = ANY(%(item_props)s)
            ),
            'text', CASE WHEN pg.kind = {lit(EVENT_COMMITMENT)} THEN n.props -> 'text' END,
            'has_text', light.props -> 'has_text',
            'dictum', light.props -> 'dictum',
            'persons', persons.value,
            'instrument', instrument.value,
            'changed_articles', {_CHANGED_ARTICLES},
            'changed_instruments', {_CHANGED_INSTRUMENTS},
            'commenced', {COMMENCED},
            {_RELATIONS},
            'matched', {matched},
            'via', {via_law},
            'coalition', {coalition_object("co")},
            'coalition_factions', {coalition_factions("co")},
            'party_choice', {voted}
        ) ORDER BY {_PAGE_ORDER}), {EMPTY_ARRAY})
        FROM page pg
        {_node_of("pg")}
        -- of a paper: whether its text is in the data and a motion's dictum, kept light
        LEFT JOIN lg_document_light light ON light.id = pg.id
        -- of a vote of the Tweede Kamer: what the coalition did (``tk-coalition-votes``)
        LEFT JOIN LATERAL (
            SELECT c.* FROM lg_decision_coalition c
            WHERE pg.kind = {lit(EVENT_VOTE)} AND c.id = pg.id
            OFFSET 0
        ) co ON true
        LEFT JOIN LATERAL (
            SELECT json_build_object(
                'key', d.key,
                'number', d.props -> 'label',
                'title', d.props -> 'title',
                'official_short', {_official_short("pg.dossier")}
            ) AS value
            FROM {COLLECTION_DOSSIERS} d
            WHERE d.label = pg.dossier
            ORDER BY d.key ASC
            LIMIT 1
        ) dossier ON true
        CROSS JOIN LATERAL (SELECT {_SIGNATURES} AS value OFFSET 0) sig
        {_PERSONS}
        LEFT JOIN LATERAL (
            SELECT json_build_object(
                'key', i.key,
                'title', {CITATION_TITLE},
                'bwb_id', i.props -> 'bwb_id',
                'article_count', i.props -> 'article_count',
                'date_in_force', i.props -> 'date_in_force',
                'kind', i.props -> 'kind'
            ) AS value
            FROM {COLLECTION_INSTRUMENTS} i
            WHERE pg.kind = {lit(EVENT_COMMENCEMENT)} AND i.key = {BWB_KEY}
        ) instrument ON true
    )"""


def _base_bind(filters: FeedFilters, limit: int) -> dict[str, Any]:
    bind: dict[str, Any] = {
        "since": filters.since or "0",
        "page_size": limit + 1,
        "cited": _CITED,
        "item_props": list(_ITEM_PROPS),
    }
    if filters.instrument:
        bind["instrument"] = filters.instrument
        bind["article"] = filters.article
    return bind


def _page_query(plan: Plan) -> str:
    """The page, with facets the total and the facets too, and the answer."""
    if not plan.facets:
        return f""",
    page AS (SELECT * FROM events ORDER BY {_ORDER} LIMIT %(page_size)s)
    SELECT json_build_object('items', {_items(plan.filters)}, 'total', NULL, 'facets', NULL)"""
    after = ""
    if plan.cursor is not None:
        after = (
            "\n        WHERE date < %(cursor_date)s OR (date = %(cursor_date)s"
            " AND (rank > %(cursor_rank)s"
            " OR (rank = %(cursor_rank)s AND id > %(cursor_id)s)))"
        )
    facets = ",\n            ".join(
        f"{lit(name)}, {dimension_facet(plan, name)}" for name in DIMENSIONS
    )
    return f""",
    matching AS (SELECT * FROM events {plan.dimensions.where()}),
    page AS (
        SELECT * FROM matching{after}
        ORDER BY {_ORDER}
        LIMIT %(page_size)s
    )
    SELECT json_build_object(
        'items', {_items(plan.filters)},
        'total', (SELECT count(*)::int FROM matching),
        'facets', json_build_object(
            {facets}
        )
    )"""


def feed_query(
    filters: FeedFilters,
    *,
    cursor: FeedCursor | None = None,
    limit: int = 50,
    facets: bool = True,
    widely_cited: bool = False,
) -> tuple[str, dict[str, Any]]:
    """The SQL of one page of the feed and its parameters. It reads ``limit + 1`` rows,
    so the caller knows whether a next page exists. *widely_cited*: the law followed is
    (``widely_cited``)."""
    bind = _base_bind(filters, limit)
    plan = Plan(
        filters=filters,
        facets=facets,
        shared=shared_filters(filters, bind),
        dimensions=dimension_filters(filters, bind),
        cursor=cursor,
        widely_cited=widely_cited,
    )
    if cursor is not None:
        bind["cursor_date"] = cursor.date
        bind["cursor_id"] = cursor.id
        bind["cursor_rank"] = cursor.rank
    bind["until"] = plan.until  # a kind reads no row after the cursor's date
    return rows_of(filters, plan, facets=facets) + _page_query(plan), bind


# The events a summary shows one by one: a bill submitted, a commitment, a commencement, a
# vote on a bill, a vote whose margin is at most ``margin``, and every vote of a quiet day.
_HIGHLIGHT = (
    f"kind IN ({lit(EVENT_BILL)}, {lit(EVENT_COMMITMENT)}, {lit(EVENT_COMMENCEMENT)})"
    f" OR (kind = {lit(EVENT_VOTE)} AND (chamber = {lit(CHAMBER_EK)}"
    " OR subkind = ANY(%(legislative)s) OR margin <= %(margin)s"
    " OR date IN (SELECT date FROM quiet_days)))"
)


# Per day of the window: the events per kind, per kind and dossier and, of the votes, per
# subkind and outcome; the title of every dossier counted; the days with at most ``few``
# votes on anything but a bill (each of their votes is shown); and the events shown one by
# one.
def _summary(dimensions: str, items: str) -> str:
    """SQL: the summary of ``events`` under *dimensions* (a WHERE), with *items*."""
    return f""",
    matching AS (SELECT * FROM events {dimensions}),
    day_kinds AS (
        SELECT date, json_agg(json_build_object('value', kind, 'count', count)
                              ORDER BY count DESC, kind ASC NULLS FIRST) AS value
        FROM (SELECT date, kind, count(*)::int AS count FROM matching GROUP BY date, kind) x
        GROUP BY date
    ),
    day_dossiers AS (
        SELECT date, json_agg(json_build_object('kind', kind, 'number', dossier, 'count', count)
                              ORDER BY rank ASC, count DESC, dossier ASC NULLS FIRST) AS value
        FROM (
            SELECT date, kind, rank, dossier, count(*)::int AS count
            FROM matching WHERE dossier IS NOT NULL
            GROUP BY date, kind, rank, dossier
        ) x
        GROUP BY date
    ),
    day_votes AS (
        SELECT date, json_agg(json_build_object(
                   'chamber', chamber, 'subkind', subkind, 'passed', passed, 'count', count)
                   ORDER BY count DESC, chamber ASC NULLS FIRST, subkind ASC NULLS FIRST,
                            passed ASC NULLS FIRST) AS value
        FROM (
            SELECT date, chamber, subkind, passed, count(*)::int AS count
            FROM matching WHERE kind = {lit(EVENT_VOTE)}
            GROUP BY date, chamber, subkind, passed
        ) x
        GROUP BY date
    ),
    days AS (
        SELECT coalesce(json_agg(json_build_object(
            'date', d.date,
            'total', d.total,
            'kinds', k.value,
            'dossiers', coalesce(ds.value, {EMPTY_ARRAY}),
            'votes', coalesce(v.value, {EMPTY_ARRAY})
        ) ORDER BY d.date DESC NULLS LAST), {EMPTY_ARRAY}) AS value
        FROM (SELECT date, count(*)::int AS total FROM matching GROUP BY date) d
        JOIN day_kinds k ON k.date = d.date
        LEFT JOIN day_dossiers ds ON ds.date = d.date
        LEFT JOIN day_votes v ON v.date = d.date
    ),
    dossier_titles AS (
        SELECT coalesce(json_agg(json_build_object(
            'number', nums.number,
            'key', d.key,
            'title', d.props -> 'title',
            'official_short', {_official_short("nums.number")}
        ) ORDER BY nums.number ASC), {EMPTY_ARRAY}) AS value
        FROM (SELECT DISTINCT dossier AS number FROM matching WHERE dossier IS NOT NULL) nums
        CROSS JOIN LATERAL (
            SELECT d.key, d.props FROM {COLLECTION_DOSSIERS} d
            WHERE d.label = nums.number
            ORDER BY d.key ASC
            LIMIT 1
        ) d
    ),
    quiet_days AS (
        SELECT date FROM matching
        WHERE kind = {lit(EVENT_VOTE)} AND chamber IS DISTINCT FROM {lit(CHAMBER_EK)}
          AND (subkind IS NULL OR subkind <> ALL(%(legislative)s))
        GROUP BY date
        HAVING count(*) <= %(few)s
    ),
    page AS (
        SELECT * FROM matching
        WHERE {_HIGHLIGHT}
        ORDER BY {_ORDER}
        LIMIT %(page_size)s
    )
    SELECT json_build_object(
        'days', (SELECT value FROM days),
        'dossiers', (SELECT value FROM dossier_titles),
        'items', {items}
    )"""


def summary_query(
    filters: FeedFilters, *, margin: int = 10, few: int = 2, limit: int = 100
) -> tuple[str, dict[str, Any]]:
    """The SQL of a summary of the days from ``filters.since`` to ``filters.until`` and its
    parameters: per day the counts (``days``), the titles of the dossiers counted, and up to
    ``limit + 1`` events shown one by one (``items``)."""
    bind = _base_bind(filters, limit)
    bind |= {"margin": margin, "few": few, "legislative": list(LEGISLATIVE_KINDS)}
    plan = Plan(
        filters=filters,
        facets=True,  # every row of the window is counted
        shared=shared_filters(filters, bind),
        dimensions=dimension_filters(filters, bind),
        cursor=None,
    )
    bind["until"] = plan.until
    summary = _summary(plan.dimensions.where(), _items(filters))
    return rows_of(filters, plan, facets=True) + summary, bind


def get_feed_summary(
    store: GraphStore,
    filters: FeedFilters,
    *,
    margin: int = 10,
    few: int = 2,
    limit: int = 100,
) -> dict[str, Any]:
    """``days``, ``dossiers`` and ``items`` of ``summary_query``, kept per data version
    (``version_cache.cached``): every visitor of the homepage asks the same one, and after a
    poll it is the one of the version before while the new one computes once (seconds on
    the full graph, past the deadline of a request while a warm-up reads)."""
    return cached(
        store,
        ("feed summary", filters, margin, few, limit),
        lambda: _summary_of(store, filters, margin=margin, few=few, limit=limit),
    )


def _summary_of(
    store: GraphStore, filters: FeedFilters, *, margin: int, few: int, limit: int
) -> dict[str, Any]:
    sql, bind = summary_query(filters, margin=margin, few=few, limit=limit)
    rows = list(store.query(sql, bind))
    return (
        cast(dict[str, Any], rows[0])
        if rows
        else {"days": [], "dossiers": [], "items": []}
    )


def get_feed(
    store: GraphStore,
    filters: FeedFilters,
    *,
    cursor: FeedCursor | None = None,
    limit: int = 50,
    facets: bool = True,
) -> dict[str, Any]:
    """One page of the feed: ``items`` (up to ``limit + 1``: one more than the page when
    there is a next page), and with *facets* ``total`` and ``facets`` (null without), or,
    while those are counted longer than ``COUNTS_BUDGET``, null and ``partial``. Words or a
    faction without a first day are searched back in windows (``_page_items``): when the
    budget ends that search, ``partial`` and ``searched_from``.

    The page is read without the facets: each kind reads its rows in date order and stops
    after one page. The total and the facets read every row under the filters (20 s on the
    full graph), whatever the cursor: they are kept per data version under the filters
    (``version_cache``)."""

    def read_page() -> tuple[list[dict[str, Any]], str | None]:
        return _page_items(store, filters, cursor, limit)

    if not facets:
        items, searched_from = read_page()
        counted: dict[str, Any] | None = {"total": None, "facets": None}
    else:
        (items, searched_from), counted = page_with_counts(
            read_page,
            lambda: _counts_of_events(store, filters) or feed_counts(store, filters),
            "The counts of the feed",
        )
    answer = with_counts(items, counted)
    if searched_from:
        answer.update(partial=True, searched_from=searched_from)
    return answer


# Words, a faction or a law without a first day (``q``, ``faction`` or ``instrument``, and no
# ``since``): a word that few events hold, a faction that signs few events of a kind (a
# letter of the government: none) or a law few events are tied to, has every event of every
# kind tested for it, the whole history (over 30 s for ``faction=vvd`` on prod, 11 Oct). The page is read back in windows,
# newest first, each of these many days further back from where it starts, then the rest,
# until it is full or ``WORDS_BUDGET`` seconds are spent: then what was found is answered,
# ``partial``, with the first day searched (``searched_from``), and a request with ``until``
# the day before goes on from there.
WORDS_WINDOWS = (90, 365, 3 * 365)
WORDS_BUDGET = 8.0


def _page_items(
    store: GraphStore, filters: FeedFilters, cursor: FeedCursor | None, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    """The rows of one page (up to ``limit + 1``) and, when the budget ended the search
    before the first event, the first day it searched."""
    if filters.since or not (
        filters.q or filters.faction or filters.party or filters.instrument
    ):
        return _rows(store, filters, cursor, limit), None
    bounded = _bounded_page(store, filters, cursor, limit)
    if bounded is not None:
        return bounded, None
    start = cursor.date[:10] if cursor else filters.until or dutch_today().isoformat()
    end = dt.date.fromisoformat(start)
    left = read_time_left()
    deadline = time.monotonic() + (
        WORDS_BUDGET if left is None else min(WORDS_BUDGET, left)
    )
    items: list[dict[str, Any]] = []
    until = filters.until
    searched_from = (end + dt.timedelta(days=1)).isoformat()  # nothing searched yet
    for days in (*WORDS_WINDOWS, None):
        since = (end - dt.timedelta(days=days)).isoformat() if days else None
        window = replace(filters, since=since, until=until)
        with read_budget(
            deadline - time.monotonic(), "The words of the feed"
        ) as budget:
            items += _rows(store, window, cursor, limit - len(items))
        if budget.ran_out:
            return items, searched_from
        if len(items) > limit or since is None:
            return items[: limit + 1], None
        searched_from = since
        until = day_before(since)
    return items, None


def _bounded_page(
    store: GraphStore, filters: FeedFilters, cursor: FeedCursor | None, limit: int
) -> list[dict[str, Any]] | None:
    """The page under words or a faction without a first day, read once from the first
    day it reaches back to (``feed_events.first_day_of_page``: by the index on the words of the events,
    not window after window); None where that table cannot tell, or the page read from that
    day is short of what it counted (an event gone since it was written): then the
    windows."""
    before = cursor.date[:10] if cursor else None
    found = feed_events.first_day_of_page(
        store, replace(filters, kinds=kinds_of(filters)), limit, before
    )
    if found is None:
        return None
    first, whole_page = found
    items = _rows(store, replace(filters, since=first), cursor, limit)
    if len(items) > limit:
        return items[: limit + 1]
    # fewer than a page: the rest of the history, unless the table held a page the feed
    # did not find
    return None if whole_page else items


def _rows(
    store: GraphStore, filters: FeedFilters, cursor: FeedCursor | None, limit: int
) -> list[dict[str, Any]]:
    """Up to ``limit + 1`` rows of the feed under *filters*, from *cursor* on."""
    sql, bind = feed_query(
        filters,
        cursor=cursor,
        limit=limit,
        facets=False,
        widely_cited=_widely_cited(store, filters),
    )
    rows = list(store.query(sql, bind))
    page = cast(dict[str, Any], rows[0]) if rows else {"items": []}
    return page.get("items") or []


# From this many citations by judgments a law followed is ``widely_cited``.
WIDELY_CITED = 5000


def _widely_cited(store: GraphStore, filters: FeedFilters) -> bool:
    """Whether the page under *filters* reads the judgments of a law (or article) cited by
    ``WIDELY_CITED`` judgments or more: its newest judgments are then found soonest in date
    order, while those of a law cited a few times are found soonest from its citations.
    Counted up to that many, by the index of the edges into its articles."""
    if not filters.instrument:
        return False
    kinds = kinds_of(filters) or FEED_KINDS
    if EVENT_JUDGMENT not in kinds:
        return False
    rows = store.query(CITATIONS_OF_LAW, {**_base_bind(filters, 0), "n": WIDELY_CITED})
    # one column: each row is its value
    return bool(next(iter(rows), False))


# How long the total and the facets of the feed under a filter are kept (seconds), whatever
# the data does: each reads every event of every kind (a minute on the full graph), and a
# run of the pipelines hardly moves them. The page itself is read fresh.
COUNTS_MAX_AGE = 3600.0


def _counts_of_events(store: GraphStore, filters: FeedFilters) -> dict[str, Any] | None:
    """``total`` and ``facets`` from ``lg_feed_events`` (by its indexes, not a read of every
    event of every kind, which takes a minute and more on prod); they follow its last
    writing. None where that table cannot tell: then ``feed_counts``."""
    return feed_events.get_counts(store, filters, COUNTS_MAX_AGE)


def feed_counts(store: GraphStore, filters: FeedFilters) -> dict[str, Any]:
    """``total`` and ``facets`` of the feed under *filters* from its own events, where
    ``lg_feed_events`` cannot tell (never written, or a filter it does not keep), kept
    ``COUNTS_MAX_AGE``. The feed without filters and that of each single kind come from
    one reading of the events for all of them (``_counts_per_kind``)."""
    kinds = _shared_kinds(filters)
    if kinds is None:
        return lasting(
            store, ("feed", filters), lambda: _counts(store, filters), COUNTS_MAX_AGE
        )
    shared = replace(filters, kinds=None)
    per_kind = lasting(
        store,
        ("feed per kind", shared),
        lambda: _counts_per_kind(store, shared),
        COUNTS_MAX_AGE,
    )
    return per_kind[kinds]


def _counts(store: GraphStore, filters: FeedFilters) -> dict[str, Any]:
    """``total`` and ``facets`` of the feed under *filters*, of every page alike."""
    sql, bind = feed_query(filters, limit=1, facets=True)
    rows = list(store.query(sql, bind))
    row = cast(dict[str, Any], rows[0]) if rows else {}
    return {"total": row.get("total"), "facets": row.get("facets")}


# The sets of kinds counted in one reading of the events: the feed without a kind (its
# ``DEFAULT_KINDS``) and every kind on its own.
_KIND_SETS: tuple[tuple[str, ...], ...] = (
    DEFAULT_KINDS,
    *((kind,) for kind in FEED_KINDS),
)


def _shared_kinds(filters: FeedFilters) -> tuple[str, ...] | None:
    """The set of ``_KIND_SETS`` *filters* asks for when it filters on nothing but the
    kind (and the dates); None when it filters on more."""
    if replace(filters, kinds=None, since=None, until=None) != FeedFilters():
        return None
    kinds = filters.kinds or DEFAULT_KINDS
    return kinds if kinds in _KIND_SETS else None


def _counts_per_kind(
    store: GraphStore, filters: FeedFilters
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Per set of ``_KIND_SETS`` the ``total`` and ``facets`` of the feed under *filters*
    (which keeps no kind), from one reading of the events: what ``_counts`` gives for each,
    in the same order (a facet by count, then by value)."""
    sql, bind = counts_per_kind_query(filters)
    rows = list(store.query(sql, bind))
    found = cast(dict[str, Any], rows[0]) if rows else {}
    totals = found.get("total") or {}
    facets = {name: found.get(name) or {} for name in DIMENSIONS if name != "kind"}
    answers: dict[tuple[str, ...], dict[str, Any]] = {}
    for n, kinds in enumerate(_KIND_SETS):
        set_id = str(n)
        answers[kinds] = {
            "total": totals.get(set_id, 0),
            "facets": {
                name: (
                    (found.get("kind") or [])
                    if name == "kind"
                    else facets[name].get(set_id, [])
                )
                for name in DIMENSIONS
            },
        }
    return answers


def counts_per_kind_query(filters: FeedFilters) -> tuple[str, dict[str, Any]]:
    """The SQL of ``_counts_per_kind`` and its parameters: the events of every kind read
    once (``events``), each counted for every set of ``_KIND_SETS`` that holds its kind."""
    bind = _base_bind(filters, 1)
    plan = Plan(
        filters=filters,
        facets=True,
        shared=shared_filters(filters, bind),
        dimensions=FacetFilters(),
        cursor=None,
    )
    bind["until"] = plan.until
    bind["set_ids"] = [str(n) for n, kinds in enumerate(_KIND_SETS) for _ in kinds]
    bind["set_kinds"] = [kind for kinds in _KIND_SETS for kind in kinds]
    per_set = ",\n        ".join(
        f"{lit(name)}, {_facet_per_set(name)}" for name in DIMENSIONS if name != "kind"
    )
    return (
        rows_of(filters, plan, facets=True)
        + f""",
    in_set AS (
        SELECT s.set_id, e.*
        FROM events e
        JOIN unnest(%(set_ids)s::text[], %(set_kinds)s::text[]) AS s(set_id, kind)
            ON s.kind = e.kind
    )
    SELECT json_build_object(
        'total', (SELECT json_object_agg(set_id, n) FROM (
            SELECT set_id, count(*)::int AS n FROM in_set GROUP BY set_id) t),
        'kind', {facet("kind", "events")},
        {per_set}
    )""",
        bind,
    )


def _facet_per_set(name: str) -> str:
    """SQL: per set of ``in_set`` the facet *name*, as ``dimension_facet`` counts it (no other
    filter than the set's kinds), by set id."""
    if name == "cabinet":
        counted = f"""SELECT set_id, value, sum(n)::int AS count FROM (
                SELECT set_id, {cabinet_on("per_day.date")} AS value, per_day.n
                FROM (SELECT set_id, date, count(*) AS n FROM in_set
                      GROUP BY set_id, date) per_day
            ) dated GROUP BY set_id, value"""
    elif name == "faction":
        counted = f"""SELECT set_id, value, count(*)::int AS count FROM (
                SELECT DISTINCT set_id, fx.faction AS value, id
                FROM {per_faction("in_set")}
            ) once GROUP BY set_id, value"""
    elif name == "coalition":
        counted = f"""SELECT set_id, value, count(*)::int AS count
            FROM {per_coalition("in_set")}
            GROUP BY set_id, value"""
    else:
        counted = f"""SELECT set_id, {name} AS value, count(*)::int AS count
            FROM in_set GROUP BY set_id, value"""
    return f"""(SELECT json_object_agg(set_id, facet) FROM (
            SELECT set_id, {FACET_AGG} AS facet
            FROM ({counted}) counted
            GROUP BY set_id
        ) per_set)"""
