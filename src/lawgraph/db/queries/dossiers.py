"""Queries behind the dossier endpoints, and the read-time stage fallback."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.config.constants import (
    CHAMBER_EK,
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    EDGE_STATUS_CANONIEK,
    EDGE_STATUS_VOORGESTELD,
    RELATION_ABOUT,
    RELATION_ACCOMPANIES,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_RELATED_TO,
    RELATION_REPEALS,
    RELATION_REVISES,
    RELATION_SECOND_READING_OF,
)
from lawgraph.core.documents import chamber_of, is_explanatory, numbered_in
from lawgraph.core.dossier_numbers import parse_dossier_query, suffix_sort_key
from lawgraph.core.dossier_stages import ACTIVITY_PLANNED, opened_on, select_title
from lawgraph.core.models import NodeType, make_node_key
from lawgraph.core.tk_links import tk_url
from lawgraph.db import GraphStore
from lawgraph.db._rows import edge_doc, node_doc
from lawgraph.db.queries.normalize import tk as normalize_tk

# Edges that put an article in flux, and the one that only explains it. The
# frontend renders the two as separate overlays.
MUTATION_RELATIONS = (
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
    RELATION_REFERS_TO,
)
EXPLANATION_RELATIONS = (RELATION_EXPLAINS,)

# How an instrument is tied to a dossier, in the order the hub lists them: legislated in
# it, then changed by it.
HUB_INSTRUMENT_RELATIONS = (
    RELATION_LEGISLATED_IN,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
)

# The relations between two dossiers, in the order the detail lists them.
DOSSIER_RELATIONS = (
    RELATION_REVISES,
    RELATION_ACCOMPANIES,
    RELATION_RELATED_TO,
    RELATION_SECOND_READING_OF,
)

_DICTUM_EXCERPT_CHARS = 280

# The props of a timeline node that its entry shows, per node type. A document's
# ``text`` and ``raw`` are not among them: the timeline is not where a document is read.
_TIMELINE_BODY_PROPS: dict[str, list[str]] = {
    "document": [
        "kind",
        "title",
        "sequence",
        "number",
        "dossier_number",
        "dossier_suffix",
        "session_year",
        "document_number",
        "url",
        "source",
    ],
    "activity": [
        "kind",
        "agenda_title",
        "number",
        "status",
        "chamber",
        "time",
        "source_url",
        "retrieved_on",
    ],
    "decision": [
        "subject",
        "chamber",
        "result",
        "method",
        "passed",
        "vote_kind",
        "tally",
        "voters",
        "decision_id",
        "primary_case_id",
        "primary_case_kind",
    ],
    "commitment": [
        "text",
        "minister_name",
        "minister_role",
        "status",
        "expected_resolution",
    ],
}

# TK writes 'Eerste ondertekenaar' / 'Mede ondertekenaar'; the frontend shows
# who submitted a document and who co-signed it.
_SIGNATORY_ROLES = {
    "eerste ondertekenaar": "indiener",
    "mede ondertekenaar": "mede-indiener",
    "medeondertekenaar": "mede-indiener",
    "indiener": "indiener",
}


# ── SQL pieces ────────────────────────────────────────────────────────────────


def _present(value: str) -> str:
    """``value != null`` of a json value: neither missing nor a json null."""
    return f"coalesce(json_typeof({value}), 'null') <> 'null'"


def _not_null(first: str, second: str) -> str:
    """``first != null ? first : second`` of two json values."""
    return f"CASE WHEN {_present(first)} THEN {first} ELSE {second} END"


def _type_rank(value: str) -> str:
    """The place of a json value's type in ArangoDB's order of types."""
    return (
        f"CASE coalesce(json_typeof({value}), 'null') WHEN 'null' THEN 0"
        " WHEN 'boolean' THEN 1 WHEN 'number' THEN 2 WHEN 'string' THEN 3"
        " WHEN 'array' THEN 4 ELSE 5 END"
    )


def _json_keys(value: str) -> list[str]:
    """The keys that sort a json value as ArangoDB does: by its type (null, boolean,
    number, string, array, object), then a string by the collation, a number, a boolean
    (two arrays or objects are equal)."""
    return [
        _type_rank(value),
        *(f"{f}({value})" for f in ("lg_str", "lg_num", "lg_bool")),
    ]


def _json_order(value: str, direction: str) -> str:
    """ORDER BY items that sort a json value as ArangoDB does (``_json_keys``)."""
    nulls = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
    return ", ".join(f"{key} {direction} {nulls}" for key in _json_keys(value))


def _as_text(value: str) -> str:
    """``TO_STRING`` of a json value as ``LOWER`` and ``LEFT`` read it: a string as it is,
    a number or a boolean as written, null as ''."""
    return f"coalesce({value} #>> '{{}}', '')"


# The documents of one dossier (``%(dossier_id)s``): directly PART_OF it, or PART_OF a
# case that is PART_OF it; each once.
_DOSSIER_DOCUMENT_IDS = f"""
    SELECT e.from_id AS id
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = %(dossier_id)s AND e.relation = %(part_of)s
      AND e.from_collection = '{COLLECTION_DOCUMENTS}'
    UNION
    SELECT e2.from_id
    FROM {COLLECTION_EDGES} e1
    JOIN {COLLECTION_EDGES} e2
      ON e2.to_id = e1.from_id AND e2.relation = %(part_of)s
     AND e2.from_collection = '{COLLECTION_DOCUMENTS}'
    WHERE e1.to_id = %(dossier_id)s AND e1.relation = %(part_of)s
      AND e1.from_collection = '{COLLECTION_CASES}'
"""


@dataclass
class DossierEnrichment:
    """What a dossier's linked documents say about it, derived at read time."""

    title: str | None = None
    title_source: str | None = None
    opened_on: str | None = None


def enrich_dossier_docs(
    store: GraphStore, dossiers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill the title (and opening date) of a dossier without one from its documents.

    Its kind and phases are written by ``normalize tk-dossiers`` alone: a dossier without
    them has none.
    """
    if all((doc.get("props") or {}).get("title") for doc in dossiers):
        for doc in dossiers:
            props = doc.setdefault("props", {})
            if not props.get("title_source"):
                props["title_source"] = "dossier"
        return dossiers

    enrichments = _enrich_dossiers(store, dossiers)
    for doc in dossiers:
        props = doc.setdefault("props", {})
        enrichment = enrichments.get(doc["_id"])
        if enrichment is None:
            continue
        if not props.get("title") and enrichment.title:
            props["title"] = enrichment.title
            props["title_source"] = enrichment.title_source
        elif props.get("title") and not props.get("title_source"):
            props["title_source"] = "dossier"
        if not props.get("opened_on") and enrichment.opened_on:
            props["opened_on"] = enrichment.opened_on
    return dossiers


def _enrich_dossiers(
    store: GraphStore, dossiers: list[dict[str, Any]]
) -> dict[str, DossierEnrichment]:
    """Title and opening date for a batch of dossiers, from the signals ``normalize
    tk-dossiers`` reads."""
    if not dossiers:
        return {}
    rows = {
        row["dossier_id"]: row
        for row in normalize_tk.dossier_signals(store, [d["_id"] for d in dossiers])
    }
    enriched: dict[str, DossierEnrichment] = {}
    for dossier in dossiers:
        row = rows.get(dossier["_id"]) or {}
        docs = row.get("docs") or []
        props = dossier.get("props") or {}
        title, title_source = select_title(props, docs)
        day, _ = opened_on(
            props.get("number"), props.get("suffix"), docs, row.get("activities") or []
        )
        enriched[dossier["_id"]] = DossierEnrichment(
            title=title, title_source=title_source, opened_on=day
        )
    return enriched


def get_dossier_by_number(
    store: GraphStore, dossier_number: str
) -> dict[str, Any] | None:
    """One dossier by its kamerstuk number (``36558``, or ``37020-XV`` for a chapter)."""
    return store.get_document(COLLECTION_DOSSIERS, make_node_key(dossier_number))


# The props a timeline row reads: what its entry shows, and its date, kind, title and
# status.
_TIMELINE_KEYS = sorted(
    {key for keys in _TIMELINE_BODY_PROPS.values() for key in keys}
    | {"date", "made_on", "kind", "display_name", "status"}
)

# The nodes PART_OF or ABOUT the dossier, one row per edge, from the four collections a
# timeline shows; their props cut down to ``_TIMELINE_KEYS`` in one pass (a TK document
# carries its whole API payload, which every ``props -> 'x'`` would parse again).
_TIMELINE_MEMBERS = "\n    UNION ALL\n".join(
    f"""    SELECT n.id, n.type, n.labels, (
        SELECT json_object_agg(k.key, k.value)
        FROM json_each(n.props) AS k(key, value)
        WHERE k.key = ANY(%(timeline_keys)s::text[])
    ) AS props
    FROM {COLLECTION_EDGES} e
    JOIN {collection} n ON n.id = e.from_id
    WHERE e.to_id = %(dossier_id)s AND e.relation = ANY(%(relations)s)
      AND e.from_collection = '{collection}'"""
    for collection in (
        COLLECTION_DOCUMENTS,
        COLLECTION_ACTIVITIES,
        COLLECTION_DECISIONS,
        COLLECTION_COMMITMENTS,
    )
)

# The props of a node its entry shows (``KEEP``): ArangoDB gives them in byte order.
_BODY_PROPS = " ".join(
    f"WHEN '{node_type}' THEN %(body_{node_type})s::text[]"
    for node_type in _TIMELINE_BODY_PROPS
)
_TIMELINE_BODY = f"""(
            SELECT coalesce(json_object_agg(k.key, k.value ORDER BY k.key COLLATE "C"), '{{}}'::json)
            FROM json_each(m.props) AS k(key, value)
            WHERE k.key = ANY(CASE m.type {_BODY_PROPS} END)
        )"""


def get_dossier_timeline(
    store: GraphStore,
    dossier_id: str,
    *,
    order: Literal["desc", "asc"] = "desc",
    kind_filter: list[str] | None = None,
    include_planned: bool = True,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Everything that happened in a dossier, in date order.

    Documents are PART_OF the dossier; activities, decisions and commitments
    are ABOUT it. A row carries the props its entry shows (``body``, see
    ``_TIMELINE_BODY_PROPS``) and the node's ``labels``; an activity row also its
    lead committee (``committee``, null for plenary), looked up for the page only.
    A decision entry carries the motion or amendment it decided on, with its
    dictum excerpt and signatories. ``after_closure`` marks a row dated after the day
    the dossier closed (``closed_on``), ``planned`` an activity still ``Gepland``; without
    *include_planned* those are left out.
    """
    bind: dict[str, Any] = {
        "dossier_id": dossier_id,
        "limit": limit,
        "relations": [RELATION_PART_OF, RELATION_ABOUT],
        "led_by": RELATION_LED_BY,
        "planned_status": ACTIVITY_PLANNED,
        "include_planned": include_planned,
        **{f"body_{t}": props for t, props in _TIMELINE_BODY_PROPS.items()},
        "timeline_keys": _TIMELINE_KEYS,
    }
    kind_clause = ""
    if kind_filter:
        kind_clause = f"AND lower({_as_text('x.kind')}) = ANY(%(kind_filter)s)"
        bind["kind_filter"] = [k.lower() for k in kind_filter]
    direction = "DESC" if order == "desc" else "ASC"
    date = _not_null("m.props -> 'date'", "m.props -> 'made_on'")
    kind = _not_null(
        "m.props -> 'kind'",
        "to_json(CASE m.type WHEN 'activity' THEN 'Activiteit'"
        " WHEN 'decision' THEN 'Stemming' WHEN 'commitment' THEN 'Toezegging'"
        " ELSE 'Document' END)",
    )
    closed_on = f"""(
        SELECT ds.pj_closed_on FROM {COLLECTION_DOSSIERS} ds
        WHERE ds.id = %(dossier_id)s
    )"""
    # MERGE adds ``after_closure`` and ``committee`` in the order ArangoDB gives them
    # (that of a hash map).
    sql = f"""
    WITH members AS MATERIALIZED (
{_TIMELINE_MEMBERS}
    ),
    entries AS (
        SELECT m.id, m.type, {date} AS date, {kind} AS kind,
               m.props -> 'display_name' AS title, {_TIMELINE_BODY} AS body,
               to_json(m.labels) AS labels,
               coalesce(m.type = 'activity'
                        AND lg_str(m.props -> 'status') = %(planned_status)s, false)
                   AS planned
        FROM members m
    ),
    page AS (
        SELECT x.*
        FROM entries x
        WHERE x.date IS NOT NULL AND {_present("x.date")}
          AND (%(include_planned)s OR NOT x.planned)
          {kind_clause}
        ORDER BY {_json_order("x.date", direction)}, x.id {direction}
        LIMIT %(limit)s
    ),
    closing AS (SELECT {closed_on} AS closed_on)
    SELECT lg_merge(
        json_build_object(
            'date', p.date,
            'kind', p.kind,
            'title', p.title,
            'body', p.body,
            'labels', p.labels,
            'node_id', p.id,
            'node_type', p.type,
            'planned', p.planned
        ),
        json_build_object(
            'after_closure', coalesce(
                {_present("closing.closed_on")}
                AND left({_as_text("p.date")}, 10)
                    > left({_as_text("closing.closed_on")}, 10),
                false
            ),
            'committee', CASE WHEN p.type = 'activity' THEN (
                SELECT json_build_object(
                    'key', c.key,
                    'slug', c.props -> 'slug',
                    'name', c.props -> 'name'
                )
                FROM {COLLECTION_EDGES} led
                JOIN {COLLECTION_COMMITTEES} c ON c.id = led.to_id
                WHERE led.from_id = p.id AND led.relation = %(led_by)s
                ORDER BY led.to_id ASC
                LIMIT 1
            ) END
        )
    )
    FROM page p CROSS JOIN closing
    ORDER BY {_json_order("p.date", direction)}, p.id {direction}
    """
    rows = list(store.query(sql, bind))
    _attach_decision_documents(store, dossier_id, rows)
    return rows


def _attach_decision_documents(
    store: GraphStore, dossier_id: str, rows: list[dict[str, Any]]
) -> None:
    """Inline the document behind every decision row, resolved case by case."""
    decisions = [row for row in rows if row.get("node_type") == "decision"]
    if not decisions:
        return
    by_case = _documents_by_case(store, dossier_id)
    for row in decisions:
        body = row.get("body") or {}
        document = by_case.get(str(body.get("primary_case_id") or ""))
        if document is None:
            continue
        body["document"] = _document_summary(document)
        row["body"] = body


def _documents_by_case(store: GraphStore, dossier_id: str) -> dict[str, dict[str, Any]]:
    """Case id -> one document PART_OF it, for every document in this dossier."""
    # The oldest document of a case is the one kept for it (the key settles a tie), as
    # ``get_decision_document`` picks it.
    sql = f"""
    SELECT c.case_id, d.id, d.key, d.type, d.labels, d.props
    FROM {COLLECTION_DOCUMENTS} d
    CROSS JOIN LATERAL json_array_elements(
        CASE WHEN json_typeof(d.props -> 'case_ids') = 'array'
             THEN d.props -> 'case_ids' ELSE '[]'::json END
    ) WITH ORDINALITY AS c(case_id, n)
    WHERE d.id IN ({_DOSSIER_DOCUMENT_IDS})
    ORDER BY {_json_order("d.props -> 'date'", "ASC")}, d.key ASC, c.n
    """
    bind = {"dossier_id": dossier_id, "part_of": RELATION_PART_OF}
    by_case: dict[str, dict[str, Any]] = {}
    for row in store.query(sql, bind):
        by_case.setdefault(str(row["case_id"]), node_doc(row))
    return by_case


def _document_summary(document: dict[str, Any]) -> dict[str, Any]:
    """The part of a document a timeline entry shows: what it says and who signed."""
    props = document.get("props") or {}
    text = props.get("text") or ""
    signatories = []
    for actor in props.get("actors") or []:
        role = _SIGNATORY_ROLES.get((actor.get("role") or "").strip().lower())
        if not role:
            continue
        signatories.append(
            {
                "member_key": actor.get("person_id") or None,
                "name": actor.get("name"),
                "party": actor.get("faction"),
                "role": role,
                "source_role": actor.get("role") or "",
                "function": actor.get("function"),
                "capacity": actor.get("capacity"),
            }
        )
    return {
        "key": document.get("_key"),
        "id": document.get("_id"),
        "kind": props.get("kind"),
        "title": props.get("title"),
        "sequence": props.get("sequence"),
        "dossier_number": numbered_in(
            props.get("dossier_number"), props.get("dossier_suffix")
        ),
        "session_year": props.get("session_year"),
        "date": props.get("date"),
        "tk_url": tk_url(NodeType.DOCUMENT.value, props),
        "source": props.get("source"),
        "chamber": chamber_of(document.get("labels")),
        "is_explanatory": is_explanatory(props.get("kind")),
        "dictum_excerpt": " ".join(text.split())[:_DICTUM_EXCERPT_CHARS] or None,
        "signatories": signatories,
    }


# The props a row of a dossier's documents shows, read from the document's props in one
# pass (a TK document carries its whole API payload, which every ``props -> 'x'`` would
# parse again).
_DOSSIER_DOCUMENT_KEYS = [
    "date",
    "display_name",
    "document_number",
    "dossier_number",
    "dossier_suffix",
    "kind",
    "sequence",
    "session_year",
    "source",
    "title",
]

# A document row of the dossier documents, in the order of the answer.
_DOSSIER_DOCUMENT_ROW = f"""json_build_object(
            'id', d.id,
            'key', d.key,
            'kind', dp.props -> 'kind',
            'title', {_not_null("dp.props -> 'title'", "dp.props -> 'display_name'")},
            'sequence', dp.props -> 'sequence',
            'dossier_number', dp.props -> 'dossier_number',
            'dossier_suffix', dp.props -> 'dossier_suffix',
            'session_year', dp.props -> 'session_year',
            'date', dp.props -> 'date',
            'document_number', dp.props -> 'document_number',
            'display_name', dp.props -> 'display_name',
            'source', dp.props -> 'source',
            'labels', to_json(d.labels)
        )"""

# The place of a document's date in ArangoDB's order (``_json_keys``) besides the string
# column ``date``: its props are read only for a document whose date is not a string.
_DATE_KEYS = f"""CASE WHEN d.date IS NULL THEN {_type_rank("d.props -> 'date'")} ELSE 3 END
            AS date_rank,
        CASE WHEN d.date IS NULL THEN lg_num(d.props -> 'date') END AS date_num,
        CASE WHEN d.date IS NULL THEN lg_bool(d.props -> 'date') END AS date_bool"""

# Newest first, the key settling a day.
_DOSSIER_DOCUMENT_ORDER = (
    "d.date_rank DESC NULLS LAST, d.date DESC NULLS LAST, d.date_num DESC NULLS LAST,"
    " d.date_bool DESC NULLS LAST, d.key ASC"
)


def get_dossier_documents(
    store: GraphStore,
    dossier_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of the documents in a dossier, newest first."""
    sql = f"""
    WITH docs AS MATERIALIZED (
        SELECT d.id, d.key, d.date, {_DATE_KEYS}
        FROM {COLLECTION_DOCUMENTS} d
        WHERE d.id IN ({_DOSSIER_DOCUMENT_IDS})
    ),
    page AS (
        SELECT d.id, row_number() OVER (ORDER BY {_DOSSIER_DOCUMENT_ORDER}) AS n
        FROM docs d
        ORDER BY {_DOSSIER_DOCUMENT_ORDER}
        OFFSET %(offset)s LIMIT %(limit)s
    )
    SELECT
        (SELECT count(*)::int FROM docs) AS total,
        (
            SELECT coalesce(json_agg({_DOSSIER_DOCUMENT_ROW} ORDER BY page.n), '[]'::json)
            FROM page JOIN {COLLECTION_DOCUMENTS} d ON d.id = page.id
            CROSS JOIN LATERAL (
                SELECT json_object_agg(k.key, k.value) AS props
                FROM json_each(d.props) AS k(key, value)
                WHERE k.key = ANY(%(row_keys)s::text[])
            ) dp
        ) AS items
    """
    bind = {
        "row_keys": _DOSSIER_DOCUMENT_KEYS,
        "dossier_id": dossier_id,
        "limit": limit,
        "offset": offset,
        "part_of": RELATION_PART_OF,
    }
    rows = list(store.query(sql, bind))
    return rows[0] if rows else {"total": 0, "items": []}


# ``legislated``: the instruments LEGISLATED_IN the dossier, an amending publication marked;
# ``changed``: what those publications and the dossier's documents AMEND, INTRODUCE or
# REPEAL, each (target, relation, status) once; ``links``: the instrument of each, itself or
# the instrument its article is PART_OF, with a status (canonical when the edge has none).
_DOSSIER_HUB_SQL = f"""
WITH docs AS MATERIALIZED (
    SELECT d.id, d.date, d.labels, {_DATE_KEYS},
        CASE WHEN d.date IS NULL THEN d.props -> 'date' ELSE to_json(d.date) END
            AS date_value,
        CASE WHEN d.kind IS NULL THEN {_type_rank("d.props -> 'kind'")} ELSE 3 END
            AS kind_rank,
        coalesce(d.kind, d.props -> 'kind' #>> '{{}}') AS kind_text,
        CASE WHEN d.kind IS NULL THEN lg_num(d.props -> 'kind') END AS kind_num
    FROM {COLLECTION_DOCUMENTS} d
    WHERE d.id IN ({_DOSSIER_DOCUMENT_IDS})
),
legislated AS (
    SELECT s.id, {_present("s.props -> 'publication_kind'")} AS publication
    FROM {COLLECTION_EDGES} e
    JOIN {COLLECTION_INSTRUMENTS} s ON s.id = e.from_id
    WHERE e.to_id = %(dossier_id)s AND e.relation = %(legislated_in)s
      AND e.from_collection = '{COLLECTION_INSTRUMENTS}'
),
targets AS (
    SELECT e.to_id AS target, e.relation, e.status
    FROM legislated s
    JOIN {COLLECTION_EDGES} e ON e.from_id = s.id AND e.relation = ANY(%(changes)s)
    WHERE s.publication
    UNION ALL
    SELECT e.to_id, e.relation, e.status
    FROM docs d
    JOIN {COLLECTION_EDGES} e ON e.from_id = d.id AND e.relation = ANY(%(changes)s)
),
changed AS (
    SELECT DISTINCT t.target, t.relation, t.status FROM targets t
),
links AS (
    SELECT s.id AS instrument_id, %(legislated_in)s::text AS relation,
           %(canonical)s::text AS status
    FROM legislated s
    WHERE NOT s.publication
    UNION ALL
    SELECT c.target, c.relation, coalesce(c.status, %(canonical)s)
    FROM changed c
    WHERE split_part(c.target, '/', 1) = '{COLLECTION_INSTRUMENTS}'
    UNION ALL
    SELECT p.to_id, c.relation, coalesce(c.status, %(canonical)s)
    FROM changed c
    JOIN {COLLECTION_EDGES} p
      ON p.from_id = c.target AND p.relation = %(part_of)s
     AND p.to_collection = '{COLLECTION_INSTRUMENTS}'
    WHERE split_part(c.target, '/', 1) <> '{COLLECTION_INSTRUMENTS}'
),
hub_instruments AS (
    SELECT DISTINCT l.instrument_id, l.relation, l.status FROM links l
),
activity_ids AS (
    SELECT e.from_id AS id
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = %(dossier_id)s AND e.relation = %(about)s
      AND e.from_collection = '{COLLECTION_ACTIVITIES}'
    UNION
    SELECT e2.from_id
    FROM {COLLECTION_EDGES} e1
    JOIN {COLLECTION_EDGES} e2
      ON e2.to_id = e1.from_id AND e2.relation = %(about)s
     AND e2.from_collection = '{COLLECTION_ACTIVITIES}'
    WHERE e1.to_id = %(dossier_id)s AND e1.relation = %(part_of)s
      AND e1.from_collection = '{COLLECTION_CASES}'
),
lead_ids AS (
    SELECT DISTINCT led.to_id AS id
    FROM activity_ids a
    JOIN {COLLECTION_EDGES} led ON led.from_id = a.id AND led.relation = %(led_by)s
)
SELECT
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', i.id,
            'key', i.key,
            'bwb_id', i.props -> 'bwb_id',
            'celex', i.props -> 'celex',
            'display_name', i.props -> 'display_name',
            'jurisdiction', i.props -> 'jurisdiction',
            'relation', lower(h.relation),
            'status', h.status
        ) ORDER BY
            coalesce(array_position(%(relation_order)s::text[], lower(h.relation)), 0) ASC,
            h.status ASC NULLS FIRST,
            {_json_order("i.props -> 'display_name'", "ASC")},
            i.key ASC
        ), '[]'::json)
        FROM hub_instruments h
        JOIN {COLLECTION_INSTRUMENTS} i ON i.id = h.instrument_id
    ) AS instruments,
    (
        SELECT coalesce(json_agg(json_build_object(
            'id', c.id,
            'key', c.key,
            'slug', c.props -> 'slug',
            'name', c.props -> 'name',
            'abbreviation', c.props -> 'abbreviation'
        ) ORDER BY {_json_order("c.props -> 'name'", "ASC")}, c.key ASC), '[]'::json)
        FROM lead_ids l
        JOIN {COLLECTION_COMMITTEES} c ON c.id = l.id
    ) AS committees,
    (
        SELECT coalesce(json_object_agg(k.kind_text, k.total ORDER BY
            k.kind_rank ASC NULLS FIRST, k.kind_num ASC NULLS FIRST, k.kind_text ASC NULLS FIRST
        ), '{{}}'::json)
        FROM (
            SELECT d.kind_rank, d.kind_num, d.kind_text, count(*)::int AS total
            FROM docs d
            WHERE d.kind_rank > 0 AND NOT (d.kind_rank = 3 AND d.kind_text = '')
            GROUP BY 1, 2, 3
        ) k
    ) AS documents_by_kind,
    (
        SELECT json_build_object(
            'document_count', count(*)::int,
            'first_date', (
                SELECT f.date_value
                FROM docs f
                WHERE '{CHAMBER_EK}' = ANY(f.labels) AND f.date_rank > 0
                ORDER BY f.date_rank ASC NULLS FIRST, f.date ASC NULLS FIRST,
                         f.date_num ASC NULLS FIRST, f.date_bool ASC NULLS FIRST
                LIMIT 1
            )
        )
        FROM docs d
        WHERE '{CHAMBER_EK}' = ANY(d.labels)
    ) AS senate
"""


def get_dossier_hub(store: GraphStore, dossier_id: str) -> dict[str, Any]:
    """What a dossier is linked to, in one query: instruments, committees, documents.

    *instruments* are the parent instruments the dossier is tied to, one row per
    ``(instrument, relation, status)``: a regulation ``LEGISLATED_IN`` the dossier; an
    instrument that an amending publication legislated in this dossier, or a bill of
    the dossier, ``AMENDS`` / ``INTRODUCES`` / ``REPEALS`` (through its articles or
    directly). *committees* lead an activity about the dossier, directly or through a
    case. *documents_by_kind* counts the documents of ``GET /api/dossiers/{n}/documents``
    (by the kinds in their order); *senate* the Eerste Kamer papers among them.
    """
    bind = {
        "dossier_id": dossier_id,
        "part_of": RELATION_PART_OF,
        "about": RELATION_ABOUT,
        "led_by": RELATION_LED_BY,
        "legislated_in": RELATION_LEGISLATED_IN,
        "changes": [RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS],
        "canonical": EDGE_STATUS_CANONIEK,
        "relation_order": [r.lower() for r in HUB_INSTRUMENT_RELATIONS],
    }
    rows = list(store.query(_DOSSIER_HUB_SQL, bind))
    return rows[0] if rows else {}


def classify_relation(relation: str | None) -> str:
    """Whether an edge proposes a change to an article or only explains it."""
    return "explanation" if relation in EXPLANATION_RELATIONS else "mutation"


# An edge of a mutation subgraph with the node it leaves (any collection, ``nodes``) and
# the article it points at; either is NULL when it is gone.
_MUTATION_COLUMNS = """e.key, e.from_id, e.to_id, e.doc,
           f.id AS f_id, f.key AS f_key, f.type AS f_type, f.labels AS f_labels,
           f.props AS f_props,
           a.id AS a_id, a.key AS a_key, a.type AS a_type, a.labels AS a_labels,
           a.props AS a_props"""


def _side(row: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    """The node of a mutation row under *prefix*, or None when it is gone."""
    if row[f"{prefix}_id"] is None:
        return None
    return node_doc(
        {k: row[f"{prefix}_{k}"] for k in ("id", "key", "type", "labels", "props")}
    )


def get_dossier_mutations(store: GraphStore, dossier_id: str) -> dict[str, Any]:
    """The pending-change and explanation subgraph of a dossier.

    Primary signal: an edge out of anything that belongs to the dossier, with
    status ``voorgesteld`` or one of the change / explanation relations. When
    nothing belongs to the dossier yet, the same relations are scoped by the
    documents that name its number. Each node takes the strongest kind of its
    edges, so a change outweighs an explanation.
    """
    sql = f"""
    SELECT {_MUTATION_COLUMNS}
    FROM {COLLECTION_EDGES} e
    LEFT JOIN nodes f ON f.id = e.from_id
    LEFT JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
    WHERE e.from_id IN (
        SELECT m.from_id FROM {COLLECTION_EDGES} m
        WHERE m.to_id = %(dossier_id)s AND m.relation = ANY(%(members)s)
    )
      AND (e.status = %(proposed)s OR e.relation = ANY(%(relations)s))
      AND e.to_collection = '{COLLECTION_ARTICLES}'
    ORDER BY e.key ASC
    """
    relations = list(MUTATION_RELATIONS) + list(EXPLANATION_RELATIONS)
    bind = {
        "dossier_id": dossier_id,
        "members": [RELATION_PART_OF, RELATION_ABOUT],
        "proposed": EDGE_STATUS_VOORGESTELD,
        "relations": relations,
    }
    graph = _MutationGraph()
    for row in store.query(sql, bind):
        graph.add(edge_doc(row), _side(row, "f"), _side(row, "a"))
    if graph.nodes:
        return graph.result()

    dossier = store.get_document(COLLECTION_DOSSIERS, dossier_id.split("/", 1)[-1])
    number = str((dossier or {}).get("props", {}).get("label") or "")
    if not number:
        return {"nodes": [], "edges": []}

    # ``@number IN (dossier_numbers OR [])``: a string of the array the props hold.
    fallback = f"""
    SELECT {_MUTATION_COLUMNS}
    FROM {COLLECTION_DOCUMENTS} f
    JOIN {COLLECTION_EDGES} e ON e.from_id = f.id AND e.relation = ANY(%(relations)s)
     AND e.to_collection = '{COLLECTION_ARTICLES}'
    LEFT JOIN {COLLECTION_ARTICLES} a ON a.id = e.to_id
    WHERE f.dossier_numbers @> ARRAY[%(number)s]::text[]
    ORDER BY f.key ASC, e.key ASC
    """
    for row in store.query(fallback, {"number": number, "relations": relations}):
        graph.add(edge_doc(row), _side(row, "f"), _side(row, "a"))
    return graph.result()


class _MutationGraph:
    """Collects the nodes and edges of a mutation subgraph, kind included."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._kinds: dict[str, str] = {}

    def add(
        self,
        edge: dict[str, Any],
        from_node: dict[str, Any] | None,
        to_node: dict[str, Any] | None,
    ) -> None:
        for node in (from_node, to_node):
            if node:
                self.nodes[node["_id"]] = node
        kind = classify_relation(edge.get("relation"))
        for node_id in (edge.get("_from"), edge.get("_to")):
            if node_id and self._kinds.get(node_id) != "mutation":
                self._kinds[node_id] = kind
        self.edges.append(
            {
                "from_id": edge.get("_from"),
                "to_id": edge.get("_to"),
                "relation": edge.get("relation"),
                "status": edge.get("status"),
                "meta": edge.get("meta"),
                "kind": kind,
            }
        )

    def result(self) -> dict[str, Any]:
        return {
            "nodes": [
                {**node, "_kind": self._kinds.get(node_id, "mutation")}
                for node_id, node in self.nodes.items()
            ],
            "edges": self.edges,
        }


_TITLE = _as_text("ds.pj_title")
_SUFFIX = _as_text("ds.props -> 'suffix'")


def _subject_filter(subject: str, bind: dict[str, Any]) -> str:
    """The SQL condition on ``ds`` for a subject: a number, a label or title text.

    ``37035`` matches every dossier of that number, ``37035-XXII`` that one dossier, any other
    text the titles that contain it.
    """
    parsed = parse_dossier_query(subject)
    if parsed is None:
        bind["subject"] = subject
        return f"strpos(lower({_TITLE}), lower(%(subject)s)) > 0"
    number, suffix = parsed
    bind["subject_number"] = number
    if suffix is None:
        return "ds.number = %(subject_number)s"
    bind["subject_suffix"] = suffix
    return f"ds.number = %(subject_number)s AND upper({_SUFFIX}) = %(subject_suffix)s"


def get_dossier_relations(store: GraphStore, dossier_id: str) -> list[dict[str, Any]]:
    """The ``REVISES``, ``ACCOMPANIES`` and ``RELATED_TO`` edges between this dossier and
    others, with the other dossier and the direction.

    Ordered by relation (``DOSSIER_RELATIONS``), outgoing before incoming, and then by the
    other dossier's number and suffix; the edge key settles the rest.
    """
    sql = f"""
    SELECT r.relation, r.direction, r.meta, d.id, d.key, d.type, d.labels, d.props
    FROM (
        SELECT 0 AS side, e.key AS edge_key, e.relation, 'outgoing' AS direction,
               e.doc -> 'meta' AS meta, e.to_id AS other
        FROM {COLLECTION_EDGES} e
        WHERE e.from_id = %(dossier_id)s AND e.relation = ANY(%(relations)s)
          AND e.to_collection = '{COLLECTION_DOSSIERS}'
        UNION ALL
        SELECT 1, e.key, e.relation, 'incoming', e.doc -> 'meta', e.from_id
        FROM {COLLECTION_EDGES} e
        WHERE e.to_id = %(dossier_id)s AND e.relation = ANY(%(relations)s)
          AND e.from_collection = '{COLLECTION_DOSSIERS}'
    ) r
    JOIN {COLLECTION_DOSSIERS} d ON d.id = r.other
    ORDER BY r.side ASC NULLS FIRST, r.edge_key ASC
    """
    bind = {"dossier_id": dossier_id, "relations": list(DOSSIER_RELATIONS)}
    rows = [
        {
            "relation": row["relation"],
            "direction": row["direction"],
            "meta": row["meta"],
            "dossier": node_doc(row),
        }
        for row in store.query(sql, bind)
    ]
    return sorted(rows, key=_relation_order)


def _relation_order(row: dict[str, Any]) -> tuple[Any, ...]:
    props = row["dossier"].get("props") or {}
    number = str(props.get("number") or "")
    return (
        DOSSIER_RELATIONS.index(row["relation"]),
        row["direction"] != "outgoing",
        int(number) if number.isdigit() else 0,
        suffix_sort_key(props.get("suffix")),
    )


_STATUS = "CASE WHEN ds.closed IS TRUE THEN 'closed' ELSE 'open' END"

# The dimensions the dossier lists count as facets: the value each counts (json), without
# a value counted as its default. ``status`` is ``open`` or ``closed``.
_DOSSIER_FACETS = {
    "status": f"to_json({_STATUS})",
    "outcome": "ds.pj_outcome",
    "kind": "ds.pj_kind",
    "phase": "ds.pj_current_phase",
    "ministry": "ds.pj_ministry",
}

# The orders of a dossier list: the prop and the direction; each ends in the key, so a
# page never repeats a row. ``title`` sorts ``LOWER(title)``.
DOSSIER_SORTS = {
    "number": ("order", "ASC"),
    "opened_on": ("opened_on", "DESC"),
    "last_activity": ("last_activity", "DESC"),
    "closed_on": ("closed_on", "DESC"),
    "title": ("title", "ASC"),
}


@dataclass(frozen=True)
class DossierFilters:
    """What a dossier list keeps; None keeps everything."""

    status: str | None = None  # open, closed
    outcome: str | None = None
    kinds: tuple[str, ...] | None = None
    phases: tuple[str, ...] | None = None  # the current phase is one of them
    has_phase: tuple[str, ...] | None = None
    ministry: str | None = None
    initiative: bool | None = None
    number: str | None = None  # a prefix of the label: 36264, 37020-
    subject: str | None = None
    committee_slug: str | None = None
    opened_from: str | None = None
    opened_to: str | None = None


# ``opened_on`` against a day as ArangoDB compares: a string by the collation; null, a
# boolean or a number below every string, an array or an object above.
_OPENED_ON = "ds.pj_opened_on"
_OPENED_BELOW = (
    f"coalesce(json_typeof({_OPENED_ON}), 'null') IN ('null', 'boolean', 'number')"
)
_OPENED_ABOVE = f"json_typeof({_OPENED_ON}) IN ('array', 'object')"

# ``@has_phase ALL IN (phases OR [])[* FILTER CURRENT.done].name``
_HAS_PHASE = """%(has_phase)s::text[] <@ ARRAY(
            SELECT lg_str(p -> 'name')
            FROM json_array_elements(
                CASE WHEN json_typeof(ds.pj_phases) = 'array'
                     THEN ds.pj_phases ELSE '[]'::json END
            ) AS p
            WHERE json_typeof(p) = 'object' AND lg_truthy(p -> 'done')
        )"""

# The dossiers an activity led by the committee of ``%(committee_slug)s`` is ABOUT.
_COMMITTEE_DOSSIERS = f"""committee_dossiers AS (
    SELECT s.to_id AS id
    FROM {COLLECTION_EDGES} led
    JOIN {COLLECTION_EDGES} s
      ON s.from_id = led.from_id AND s.relation = %(about)s
     AND s.to_collection = '{COLLECTION_DOSSIERS}'
    WHERE led.relation = %(led_by)s AND led.to_id = (
        SELECT c.id FROM {COLLECTION_COMMITTEES} c
        WHERE lg_str(c.props -> 'slug') = %(committee_slug)s
        ORDER BY c.key ASC
        LIMIT 1
    )
)"""


def _dossier_filters(
    filters: DossierFilters, bind: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """The SQL conditions on ``ds``: those that hold for every facet, and those of a
    facet dimension by its name (a facet is counted without its own)."""
    own: dict[str, str] = {}
    shared: list[str] = []
    for name, value, clause in (
        ("status", filters.status, f"{_STATUS} = %(status)s"),
        ("outcome", filters.outcome, "lg_str(ds.pj_outcome) = %(outcome)s"),
        ("kind", filters.kinds, "lg_str(ds.pj_kind) = ANY(%(kind)s)"),
        ("phase", filters.phases, "lg_str(ds.pj_current_phase) = ANY(%(phase)s)"),
        ("ministry", filters.ministry, "ds.ministry = %(ministry)s"),
    ):
        if value:
            own[name] = clause
            bind[name] = list(value) if isinstance(value, tuple) else value
    if filters.number:
        # a prefix as a range, so the index on the label answers it
        shared.append("ds.label >= %(number)s AND ds.label < %(number_end)s")
        bind["number"] = filters.number
        bind["number_end"] = filters.number + "\uffff"
    if filters.subject:
        shared.append(_subject_filter(filters.subject, bind))
    if filters.has_phase:
        shared.append(_HAS_PHASE)
        bind["has_phase"] = list(filters.has_phase)
    if filters.initiative is not None:
        shared.append("lg_bool(ds.pj_initiative) = %(initiative)s")
        bind["initiative"] = filters.initiative
    if filters.opened_from:
        shared.append(f"(ds.opened_on >= %(opened_from)s OR {_OPENED_ABOVE})")
        bind["opened_from"] = filters.opened_from
    if filters.opened_to:
        shared.append(f"(ds.opened_on <= %(opened_to)s OR {_OPENED_BELOW})")
        bind["opened_to"] = filters.opened_to
    if filters.committee_slug:
        shared.append("ds.id IN (SELECT id FROM committee_dossiers)")
        bind["committee_slug"] = filters.committee_slug
        bind["led_by"] = RELATION_LED_BY
        bind["about"] = RELATION_ABOUT
    return shared, own


def _facet(name: str, own: dict[str, str]) -> str:
    """The count per value of facet *name* over ``base`` under the other dimensions'
    filters, the largest first; equal counts by value, in ArangoDB's order of values."""
    value = f"b.f_{name}"
    kept = " AND ".join(f"b.k_{n}" for n in own if n != name) or "TRUE"
    rank = _type_rank(value)
    return f"""(
        SELECT coalesce(json_agg(json_build_object('value', g.value, 'count', g.n)
                        ORDER BY g.n DESC, g.rank ASC, g.num ASC NULLS FIRST,
                                 g.txt ASC NULLS FIRST), '[]'::json)
        FROM (
            SELECT (array_agg({value}))[1] AS value, count(*)::int AS n,
                   {rank} AS rank, lg_num({value}) AS num,
                   CASE WHEN {rank} <> 2 THEN {value} #>> '{{}}' END AS txt
            FROM base b
            WHERE {kept}
            GROUP BY 3, 4, 5
        ) g
    )"""


def _sort_keys(sort: str) -> tuple[list[str], str]:
    """The expressions on ``ds`` a list sorts on, and their direction."""
    field, direction = DOSSIER_SORTS[sort]
    if field == "title":
        return [f"lower({_TITLE})"], direction
    return _json_keys(f"ds.pj_{field}"), direction


def get_dossiers(
    store: GraphStore,
    filters: DossierFilters,
    *,
    sort: str = "opened_on",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of the dossiers *filters* keeps, in the order *sort* (``DOSSIER_SORTS``),
    with ``total`` and ``facets``: per ``status``, ``outcome``, ``track``, ``stage`` (the
    current one) and ``ministry`` the number of dossiers per value under the other filters,
    each dimension counted without its own filter.

    One read of the dossiers the shared filters keep (``base``) answers the page, the total
    and every facet; the committee filter resolves that committee's dossiers once as a set.
    """
    bind: dict[str, Any] = {"limit": limit, "offset": offset}
    shared, own = _dossier_filters(filters, bind)
    keys, direction = _sort_keys(sort)
    nulls = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
    order = ", ".join(
        [f"b.s{i} {direction} {nulls}" for i in range(len(keys))] + ["b.key ASC"]
    )
    columns = ",\n               ".join(
        [f"{expression} AS s{i}" for i, expression in enumerate(keys)]
        + [f"{expression} AS f_{name}" for name, expression in _DOSSIER_FACETS.items()]
        + [f"({clause}) IS TRUE AS k_{name}" for name, clause in own.items()]
    )
    kept = " AND ".join(f"b.k_{name}" for name in own) or "TRUE"
    facets = ",\n            ".join(
        f"'{name}', {_facet(name, own)}" for name in _DOSSIER_FACETS
    )
    committee = f"{_COMMITTEE_DOSSIERS}," if filters.committee_slug else ""
    where = " AND ".join(f"({c})" for c in shared) or "TRUE"
    sql = f"""
    WITH {committee}
    base AS MATERIALIZED (
        SELECT ds.id, ds.key,
               {columns}
        FROM {COLLECTION_DOSSIERS} ds
        WHERE {where}
    ),
    kept AS (
        SELECT b.* FROM base b WHERE {kept}
    ),
    page AS (
        SELECT b.id, row_number() OVER (ORDER BY {order}) AS n
        FROM kept b
        ORDER BY {order}
        OFFSET %(offset)s LIMIT %(limit)s
    )
    SELECT
        (SELECT count(*)::int FROM kept) AS total,
        (
            SELECT coalesce(json_agg(json_build_object(
                '_key', ds.key,
                '_id', ds.id,
                'type', ds.type,
                'labels', to_json(ds.labels),
                'props', ds.props
            ) ORDER BY page.n), '[]'::json)
            FROM page JOIN {COLLECTION_DOSSIERS} ds ON ds.id = page.id
        ) AS items,
        json_build_object(
            {facets}
        ) AS facets
    """
    rows = list(store.query(sql, bind))
    return rows[0] if rows else {"total": 0, "items": [], "facets": {}}


# The members of a dossier per collection, in the order of the answer.
_MEMBER_COUNTS = ", ".join(
    f"(count(*) FILTER (WHERE e.from_collection = '{collection}'))::int AS {name}"
    for name, collection in (
        ("documents", COLLECTION_DOCUMENTS),
        ("activities", COLLECTION_ACTIVITIES),
        ("decisions", COLLECTION_DECISIONS),
        ("commitments", COLLECTION_COMMITMENTS),
    )
)


def count_dossier_members(store: GraphStore, dossier_id: str) -> dict[str, int]:
    """How many documents, activities, decisions and commitments a dossier has."""
    sql = f"""
    SELECT {_MEMBER_COUNTS}
    FROM {COLLECTION_EDGES} e
    WHERE e.to_id = %(dossier_id)s AND e.relation = ANY(%(relations)s)
    """
    bind = {"dossier_id": dossier_id, "relations": [RELATION_PART_OF, RELATION_ABOUT]}
    rows = list(store.query(sql, bind))
    return rows[0] if rows else {}


def collect_dossier_numbers(
    documents: Iterable[dict[str, Any] | None],
) -> list[str]:
    """The distinct dossier numbers named by a set of document dicts."""
    numbers = {
        str(number).strip()
        for document in documents
        for number in (document or {}).get("dossiers") or []
        if number is not None and str(number).strip()
    }
    return sorted(numbers)


def get_dossier_titles(
    store: GraphStore, numbers: Iterable[str]
) -> dict[str, str | None]:
    """Dossier node key -> title, for many dossier numbers in one query."""
    keys = sorted({make_node_key(str(n)) for n in numbers if str(n).strip()})
    if not keys:
        return {}
    rows = store.query(
        "SELECT key, props -> 'title' AS title FROM dossiers WHERE key = ANY(%(keys)s)",
        {"keys": keys},
    )
    return {row["key"]: row["title"] for row in rows}


# Of each name: the first instrument (by key) whose citation title, title or short title
# it is, in lower case; else the instrument whose citation title it begins, when one alone.
# A stub is never one.
_LAWS_NAMED_SQL = f"""
SELECT n.name,
       found.key IS NOT NULL AS loaded,
       found.key,
       found.bwb_id
FROM unnest(%(names)s::text[]) WITH ORDINALITY AS n(name, ord)
LEFT JOIN LATERAL (
    SELECT i.key, i.props -> 'bwb_id' AS bwb_id
    FROM {COLLECTION_INSTRUMENTS} i
    WHERE i.stub IS DISTINCT FROM TRUE
      AND (lower({_as_text("i.props -> 'citation_title'")}) = lower(n.name)
           OR lower({_as_text("i.props -> 'title'")}) = lower(n.name)
           OR lower({_as_text("i.props -> 'short_title'")}) = lower(n.name))
    ORDER BY i.key ASC
    LIMIT 1
) exact ON TRUE
LEFT JOIN LATERAL (
    SELECT min(b.key) AS key, (array_agg(b.bwb_id))[1] AS bwb_id, count(*) AS n
    FROM (
        SELECT i.key, i.props -> 'bwb_id' AS bwb_id
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE exact.key IS NULL AND i.stub IS DISTINCT FROM TRUE
          AND starts_with(lower({_as_text("i.props -> 'citation_title'")}),
                          lower(n.name) || ' ')
        LIMIT 2
    ) b
) begun ON TRUE
CROSS JOIN LATERAL (
    SELECT exact.key, exact.bwb_id WHERE exact.key IS NOT NULL
    UNION ALL
    SELECT begun.key, begun.bwb_id WHERE exact.key IS NULL AND begun.n = 1
    UNION ALL
    SELECT NULL, NULL WHERE exact.key IS NULL AND begun.n <> 1
) found
ORDER BY n.ord
"""


def get_laws_named(store: GraphStore, names: list[str]) -> list[dict[str, Any]]:
    """``{name, loaded, key, bwb_id}`` of each law *names* holds (the laws a dossier title
    names), found by the citation title, title or short title of an instrument; else by
    the one citation title the name begins (a name the title cut at "in")."""
    if not names:
        return []
    return list(store.query(_LAWS_NAMED_SQL, {"names": names}))


def tk_values(store: GraphStore) -> dict[str, set[str]]:
    """The values of the Tweede Kamer the database holds that a phase can name:
    ``documents`` (``Document.Soort``), ``activities`` (``Activiteit.Soort``) and
    ``decisions`` (``BesluitSoort``)."""
    # every value, of any type (``jsonb``: a scalar, to tell them apart); a paper's props
    # are read only when its kind is not a string
    sql = f"""
    SELECT
        ARRAY(
            SELECT DISTINCT to_jsonb(d.kind) FROM {COLLECTION_DOCUMENTS} d
            WHERE d.kind IS NOT NULL
            UNION
            SELECT (d.props -> 'kind')::jsonb FROM {COLLECTION_DOCUMENTS} d
            WHERE d.kind IS NULL
        ) AS documents,
        ARRAY(
            SELECT DISTINCT (a.props -> 'kind')::jsonb FROM {COLLECTION_ACTIVITIES} a
        ) AS activities,
        ARRAY(
            SELECT DISTINCT (d.props -> 'decision_kind')::jsonb
            FROM {COLLECTION_DECISIONS} d
        ) AS decisions
    """
    row = next(iter(store.query(sql)), None) or {}
    return {part: {v for v in row.get(part) or [] if v} for part in row}
