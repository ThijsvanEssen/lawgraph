"""Queries behind the dossier endpoints, and the read-time stage fallback."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

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
from lawgraph.core.documents import chamber_of, is_explanatory
from lawgraph.core.dossier_numbers import parse_dossier_query, suffix_sort_key
from lawgraph.core.dossier_stages import (
    ACTIVITY_PLANNED,
    classify_track_kind,
    dossier_stages,
    select_title,
)
from lawgraph.core.models import NodeType, make_node_key
from lawgraph.core.tk_links import tk_url
from lawgraph.db import ArangoStore

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
        "session_year",
        "document_number",
        "url",
        "source",
    ],
    "activity": ["kind", "agenda_title", "number", "status"],
    "decision": [
        "subject",
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


@dataclass
class DossierEnrichment:
    """What a dossier's linked documents say about it, derived at read time."""

    title: str | None = None
    title_source: str | None = None
    current_stage: str | None = None
    stages_present: list[str] = field(default_factory=list)
    stages_complete: bool = True
    stages_missing: list[str] = field(default_factory=list)
    track_kind: str | None = None
    opened_on: str | None = None


def enrich_dossier_docs(
    store: ArangoStore, dossiers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill the title and stage props a dossier is missing from its documents.

    The normalize pipeline writes ``stages_present`` (empty for a dossier that is no
    bill) on every dossier it touches, so the expensive walk only fires for a dossier
    it has not reached yet, or one without a title.
    """
    incomplete = any(
        not (props := doc.get("props") or {}).get("title")
        or props.get("stages_present") is None
        for doc in dossiers
    )
    if not incomplete:
        for doc in dossiers:
            props = doc.setdefault("props", {})
            if props.get("title") and not props.get("title_source"):
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
        if props.get("stages_present") is None:
            props["stages_present"] = enrichment.stages_present
            props["stages_complete"] = enrichment.stages_complete
            props["stages_missing"] = enrichment.stages_missing
        if props.get("current_stage") is None and enrichment.current_stage:
            props["current_stage"] = enrichment.current_stage
        if not props.get("track_kind") and enrichment.track_kind:
            props["track_kind"] = enrichment.track_kind
        if not props.get("opened_on") and enrichment.opened_on:
            props["opened_on"] = enrichment.opened_on
    return dossiers


def _enrich_dossiers(
    store: ArangoStore, dossiers: list[dict[str, Any]]
) -> dict[str, DossierEnrichment]:
    """Title and stage signals for a batch of dossiers, in one query."""
    if not dossiers:
        return {}

    aql = f"""
    FOR dossier_id IN @dossier_ids
        LET direct = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == dossier_id AND e.relation == @part_of
                FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
                LET document = DOCUMENT(e._from)
                FILTER document != null
                RETURN document
        )
        LET via_case = (
            FOR e1 IN {COLLECTION_EDGES}
                FILTER e1._to == dossier_id AND e1.relation == @part_of
                FILTER STARTS_WITH(e1._from, '{COLLECTION_CASES}/')
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._to == e1._from AND e2.relation == @part_of
                    FILTER STARTS_WITH(e2._from, '{COLLECTION_DOCUMENTS}/')
                    LET document = DOCUMENT(e2._from)
                    FILTER document != null
                    RETURN document
        )
        LET subjects = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == dossier_id AND e.relation == @about
                LET node = DOCUMENT(e._from)
                FILTER node != null
                RETURN node
        )
        RETURN {{
            dossier_id: dossier_id,
            docs: (
                FOR document IN UNIQUE(APPEND(direct, via_case))
                    RETURN {{
                        kind: document.props.kind,
                        date: document.props.date,
                        title: (document.props.title != null
                                ? document.props.title
                                : document.props.display_name)
                    }}
            ),
            activities: (
                FOR node IN subjects
                    FILTER STARTS_WITH(node._id, '{COLLECTION_ACTIVITIES}/')
                    RETURN {{
                        kind: node.props.kind,
                        date: node.props.date,
                        status: node.props.status
                    }}
            ),
            decisions: (
                FOR node IN subjects
                    FILTER STARTS_WITH(node._id, '{COLLECTION_DECISIONS}/')
                    RETURN {{date: node.props.date, passed: node.props.passed}}
            )
        }}
    """
    bind = {
        "dossier_ids": [d["_id"] for d in dossiers],
        "part_of": RELATION_PART_OF,
        "about": RELATION_ABOUT,
    }
    rows = {row["dossier_id"]: row for row in store.query(aql, bind)}

    enriched: dict[str, DossierEnrichment] = {}
    for dossier in dossiers:
        props = dossier.get("props") or {}
        row = rows.get(dossier["_id"]) or {}
        docs = row.get("docs") or []
        activities = row.get("activities") or []
        decisions = row.get("decisions") or []
        case_kinds = list(props.get("case_kinds") or [])

        title, title_source = select_title(props, docs)
        track_kind = classify_track_kind(
            case_kinds,
            title=title or props.get("title"),
            document_kinds=[doc.get("kind") or "" for doc in docs],
        )
        stages = dossier_stages(
            track_kind,
            docs,
            activities,
            decisions,
            case_kinds,
            closed=bool(props.get("closed")),
            outcome=props.get("outcome"),
        )
        dated = [d["date"] for d in docs + activities if d.get("date")]

        enriched[dossier["_id"]] = DossierEnrichment(
            title=title,
            title_source=title_source,
            current_stage=stages.current,
            stages_present=stages.present,
            stages_complete=stages.complete,
            stages_missing=stages.missing,
            track_kind=track_kind,
            opened_on=min(dated) if dated else None,
        )
    return enriched


def get_dossier_by_number(
    store: ArangoStore, dossier_number: str
) -> dict[str, Any] | None:
    """One dossier by its kamerstuk number (``36558``, or ``37020-XV`` for a chapter)."""
    return cast(
        dict[str, Any] | None,
        store.collection(COLLECTION_DOSSIERS).get(make_node_key(dossier_number)),
    )


def get_dossier_timeline(
    store: ArangoStore,
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
        "part_of": RELATION_PART_OF,
        "about": RELATION_ABOUT,
        "led_by": RELATION_LED_BY,
        "body_props": _TIMELINE_BODY_PROPS,
        "planned_status": ACTIVITY_PLANNED,
        "include_planned": include_planned,
    }
    kind_clause = ""
    if kind_filter:
        kind_clause = "FILTER LOWER(entry.kind) IN @kind_filter"
        bind["kind_filter"] = [k.lower() for k in kind_filter]

    aql = f"""
    LET dossier_nodes = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id
            FILTER e.relation IN [@part_of, @about]
            LET collection = SPLIT(e._from, '/')[0]
            FILTER collection IN [
                '{COLLECTION_DOCUMENTS}', '{COLLECTION_ACTIVITIES}',
                '{COLLECTION_DECISIONS}', '{COLLECTION_COMMITMENTS}'
            ]
            LET node = DOCUMENT(e._from)
            FILTER node != null
            RETURN node
    )
    LET closed_on = DOCUMENT(@dossier_id).props.closed_on
    FOR node IN dossier_nodes
        LET entry = {{
            date: (node.props.date != null ? node.props.date
                   : node.props.made_on),
            kind: (node.props.kind != null ? node.props.kind
                   : node.type == 'activity' ? 'Activiteit'
                   : node.type == 'decision' ? 'Stemming'
                   : node.type == 'commitment' ? 'Toezegging' : 'Document'),
            title: node.props.display_name,
            body: KEEP(node.props, @body_props[node.type]),
            labels: node.labels,
            node_id: node._id,
            node_type: node.type,
            planned: node.type == 'activity' AND node.props.status == @planned_status
        }}
        FILTER entry.date != null
        FILTER @include_planned OR NOT entry.planned
        {kind_clause}
        SORT entry.date {"DESC" if order == "desc" else "ASC"}
        LIMIT @limit
        LET committee = node.type == 'activity' ? FIRST(
            FOR led IN {COLLECTION_EDGES}
                FILTER led._from == node._id AND led.relation == @led_by
                LET lead = DOCUMENT(led._to)
                FILTER lead != null
                LIMIT 1
                RETURN {{
                    key: lead._key,
                    slug: lead.props.slug,
                    name: lead.props.name
                }}
        ) : null
        RETURN MERGE(entry, {{
            committee: committee,
            after_closure: closed_on != null
                AND LEFT(entry.date, 10) > LEFT(closed_on, 10)
        }})
    """
    rows = list(store.query(aql, bind))
    _attach_decision_documents(store, dossier_id, rows)
    return rows


def _attach_decision_documents(
    store: ArangoStore, dossier_id: str, rows: list[dict[str, Any]]
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


def _documents_by_case(
    store: ArangoStore, dossier_id: str
) -> dict[str, dict[str, Any]]:
    """Case id -> one document PART_OF it, for every document in this dossier."""
    aql = f"""
    LET direct = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id AND e.relation == @part_of
            FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
            LET document = DOCUMENT(e._from)
            FILTER document != null
            RETURN document
    )
    LET via_case = (
        FOR e1 IN {COLLECTION_EDGES}
            FILTER e1._to == @dossier_id AND e1.relation == @part_of
            FILTER STARTS_WITH(e1._from, '{COLLECTION_CASES}/')
            FOR e2 IN {COLLECTION_EDGES}
                FILTER e2._to == e1._from AND e2.relation == @part_of
                FILTER STARTS_WITH(e2._from, '{COLLECTION_DOCUMENTS}/')
                LET document = DOCUMENT(e2._from)
                FILTER document != null
                RETURN document
    )
    FOR document IN UNIQUE(APPEND(direct, via_case))
        FOR case_id IN (document.props.case_ids != null ? document.props.case_ids : [])
            RETURN {{ case_id: case_id, document: document }}
    """
    bind = {"dossier_id": dossier_id, "part_of": RELATION_PART_OF}
    by_case: dict[str, dict[str, Any]] = {}
    for row in store.query(aql, bind):
        by_case.setdefault(str(row["case_id"]), row["document"])
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
        "session_year": props.get("session_year"),
        "date": props.get("date"),
        "tk_url": tk_url(NodeType.DOCUMENT.value, props),
        "source": props.get("source"),
        "chamber": chamber_of(document.get("labels")),
        "is_explanatory": is_explanatory(props.get("kind")),
        "dictum_excerpt": " ".join(text.split())[:_DICTUM_EXCERPT_CHARS] or None,
        "signatories": signatories,
    }


_DOSSIER_DOCUMENT_ROW = """
            RETURN {
                id: document._id,
                key: document._key,
                kind: document.props.kind,
                title: (document.props.title != null ? document.props.title
                        : document.props.display_name),
                sequence: document.props.sequence,
                session_year: document.props.session_year,
                date: document.props.date,
                document_number: document.props.document_number,
                display_name: document.props.display_name,
                source: document.props.source,
                labels: document.labels
            }"""


def _dossier_documents_aql(body: str) -> str:
    """The documents of one dossier — directly PART_OF it, or via a case."""
    return f"""
        LET direct = (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == dossier_id AND e.relation == @part_of
                FILTER STARTS_WITH(e._from, '{COLLECTION_DOCUMENTS}/')
                LET document = DOCUMENT(e._from)
                FILTER document != null
                RETURN document
        )
        LET via_case = (
            FOR e1 IN {COLLECTION_EDGES}
                FILTER e1._to == dossier_id AND e1.relation == @part_of
                FILTER STARTS_WITH(e1._from, '{COLLECTION_CASES}/')
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._to == e1._from AND e2.relation == @part_of
                    FILTER STARTS_WITH(e2._from, '{COLLECTION_DOCUMENTS}/')
                    LET document = DOCUMENT(e2._from)
                    FILTER document != null
                    RETURN document
        )
        LET all_documents = UNIQUE(APPEND(direct, via_case))
        {body}
    """


def get_dossier_documents(
    store: ArangoStore,
    dossier_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """A page of the documents in a dossier, newest first."""
    body = f"""
        LET items = (
            FOR document IN all_documents
                SORT document.props.date DESC, document._key
                LIMIT @offset, @limit
                {_DOSSIER_DOCUMENT_ROW}
        )
        RETURN {{ total: LENGTH(all_documents), items: items }}
    """
    aql = f"LET dossier_id = @dossier_id\n{_dossier_documents_aql(body)}"
    bind = {
        "dossier_id": dossier_id,
        "limit": limit,
        "offset": offset,
        "part_of": RELATION_PART_OF,
    }
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {"total": 0, "items": []}


def get_documents_for_dossiers(
    store: ArangoStore,
    dossier_ids: list[str],
    *,
    per_dossier_limit: int = 8,
) -> dict[str, list[dict[str, Any]]]:
    """Top-N documents per dossier in one round trip, keyed by dossier ``_id``."""
    if not dossier_ids:
        return {}
    body = f"""
        LET items = (
            FOR document IN all_documents
                SORT document.props.date DESC
                LIMIT @per_dossier_limit
                {_DOSSIER_DOCUMENT_ROW}
        )
        RETURN {{ dossier_id: dossier_id, items: items }}
    """
    aql = f"FOR dossier_id IN @ids\n{_dossier_documents_aql(body)}"
    bind = {
        "ids": dossier_ids,
        "per_dossier_limit": per_dossier_limit,
        "part_of": RELATION_PART_OF,
    }
    return {row["dossier_id"]: row["items"] for row in store.query(aql, bind)}


_DOSSIER_HUB_BODY = f"""
    LET legislated_by = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == dossier_id AND e.relation == @legislated_in
            FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
            LET source = DOCUMENT(e._from)
            FILTER source != null
            RETURN {{ id: source._id, publication: source.props.publication_kind != null }}
    )
    LET regulation_rows = (
        FOR source IN legislated_by
            FILTER NOT source.publication
            RETURN {{
                instrument_id: source.id,
                relation: @legislated_in,
                status: @canonical
            }}
    )
    LET target_rows = APPEND(
        (
            FOR source IN legislated_by
                FILTER source.publication
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == source.id AND e.relation IN @changes
                    RETURN {{ target: e._to, relation: e.relation, status: e.status }}
        ),
        (
            FOR document IN all_documents
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == document._id AND e.relation IN @changes
                    RETURN {{ target: e._to, relation: e.relation, status: e.status }}
        )
    )
    LET change_rows = (
        FOR row IN target_rows
            COLLECT target = row.target, relation = row.relation, status = row.status
            LET instrument_ids = STARTS_WITH(target, '{COLLECTION_INSTRUMENTS}/')
                ? [target]
                : (
                    FOR part IN {COLLECTION_EDGES}
                        FILTER part._from == target AND part.relation == @part_of
                        FILTER STARTS_WITH(part._to, '{COLLECTION_INSTRUMENTS}/')
                        RETURN part._to
                )
            FOR instrument_id IN instrument_ids
                RETURN {{
                    instrument_id: instrument_id,
                    relation: relation,
                    status: status != null ? status : @canonical
                }}
    )
    LET instruments = (
        FOR row IN APPEND(regulation_rows, change_rows)
            COLLECT instrument_id = row.instrument_id,
                    relation = row.relation,
                    status = row.status
            LET instrument = DOCUMENT(instrument_id)
            FILTER instrument != null
            SORT POSITION(@relation_order, LOWER(relation), true), status,
                 instrument.props.display_name, instrument._key
            RETURN {{
                id: instrument._id,
                key: instrument._key,
                bwb_id: instrument.props.bwb_id,
                celex: instrument.props.celex,
                display_name: instrument.props.display_name,
                jurisdiction: instrument.props.jurisdiction,
                relation: LOWER(relation),
                status: status
            }}
    )

    LET activity_ids = UNIQUE(APPEND(
        (
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == dossier_id AND e.relation == @about
                FILTER STARTS_WITH(e._from, '{COLLECTION_ACTIVITIES}/')
                RETURN e._from
        ),
        (
            FOR e1 IN {COLLECTION_EDGES}
                FILTER e1._to == dossier_id AND e1.relation == @part_of
                FILTER STARTS_WITH(e1._from, '{COLLECTION_CASES}/')
                FOR e2 IN {COLLECTION_EDGES}
                    FILTER e2._to == e1._from AND e2.relation == @about
                    FILTER STARTS_WITH(e2._from, '{COLLECTION_ACTIVITIES}/')
                    RETURN e2._from
        )
    ))
    LET committees = (
        FOR activity_id IN activity_ids
            FOR led IN {COLLECTION_EDGES}
                FILTER led._from == activity_id AND led.relation == @led_by
                COLLECT committee_id = led._to
                LET committee = DOCUMENT(committee_id)
                FILTER committee != null
                SORT committee.props.name, committee._key
                RETURN {{
                    id: committee._id,
                    key: committee._key,
                    slug: committee.props.slug,
                    name: committee.props.name,
                    abbreviation: committee.props.abbreviation
                }}
    )

    LET kinds = MERGE(
        FOR document IN all_documents
            FILTER document.props.kind != null AND document.props.kind != ''
            COLLECT kind = document.props.kind WITH COUNT INTO total
            RETURN {{ [kind]: total }}
    )
    LET senate_dates = (
        FOR document IN all_documents
            FILTER '{CHAMBER_EK}' IN document.labels
            RETURN document.props.date
    )
    RETURN {{
        instruments: instruments,
        committees: committees,
        documents_by_kind: kinds,
        senate: {{ document_count: LENGTH(senate_dates), first_date: MIN(senate_dates) }}
    }}
"""


def get_dossier_hub(store: ArangoStore, dossier_id: str) -> dict[str, Any]:
    """What a dossier is linked to, in one query: instruments, committees, documents.

    *instruments* are the parent instruments the dossier is tied to, one row per
    ``(instrument, relation, status)``: a regulation ``LEGISLATED_IN`` the dossier; an
    instrument that an amending publication legislated in this dossier, or a bill of
    the dossier, ``AMENDS`` / ``INTRODUCES`` / ``REPEALS`` (through its articles or
    directly). *committees* lead an activity about the dossier, directly or through a
    case. *documents_by_kind* counts the documents of ``GET /api/dossiers/{n}/documents``;
    *senate* the Eerste Kamer papers among them.
    """
    aql = f"LET dossier_id = @dossier_id\n{_dossier_documents_aql(_DOSSIER_HUB_BODY)}"
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
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {}


def classify_relation(relation: str | None) -> str:
    """Whether an edge proposes a change to an article or only explains it."""
    return "explanation" if relation in EXPLANATION_RELATIONS else "mutation"


def get_dossier_mutations(store: ArangoStore, dossier_id: str) -> dict[str, Any]:
    """The pending-change and explanation subgraph of a dossier.

    Primary signal: an edge out of anything that belongs to the dossier, with
    status ``voorgesteld`` or one of the change / explanation relations. When
    nothing belongs to the dossier yet, the same relations are scoped by the
    documents that name its number. Each node takes the strongest kind of its
    edges, so a change outweighs an explanation.
    """
    aql = f"""
    LET member_ids = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id
            FILTER e.relation IN [@part_of, @about]
            RETURN e._from
    )
    FOR e IN {COLLECTION_EDGES}
        FILTER e._from IN member_ids
        FILTER e.status == @proposed OR e.relation IN @relations
        FILTER STARTS_WITH(e._to, "{COLLECTION_ARTICLES}/")
        RETURN {{ edge: e, from_node: DOCUMENT(e._from), to_node: DOCUMENT(e._to) }}
    """
    relations = list(MUTATION_RELATIONS) + list(EXPLANATION_RELATIONS)
    bind = {
        "dossier_id": dossier_id,
        "part_of": RELATION_PART_OF,
        "about": RELATION_ABOUT,
        "proposed": EDGE_STATUS_VOORGESTELD,
        "relations": relations,
    }
    graph = _MutationGraph()
    for row in store.query(aql, bind):
        graph.add(row.get("edge") or {}, row.get("from_node"), row.get("to_node"))
    if graph.nodes:
        return graph.result()

    dossier = cast(
        dict[str, Any] | None,
        store.collection(COLLECTION_DOSSIERS).get(dossier_id.split("/", 1)[-1]),
    )
    number = str((dossier or {}).get("props", {}).get("label") or "")
    if not number:
        return {"nodes": [], "edges": []}

    fallback = f"""
    FOR document IN {COLLECTION_DOCUMENTS}
        FILTER @number IN (document.props.dossier_numbers OR [])
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == document._id AND e.relation IN @relations
            FILTER STARTS_WITH(e._to, "{COLLECTION_ARTICLES}/")
            RETURN DISTINCT {{
                edge: e, from_node: document, to_node: DOCUMENT(e._to)
            }}
    """
    for row in store.query(fallback, {"number": number, "relations": relations}):
        graph.add(row["edge"], row.get("from_node"), row.get("to_node"))
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


def _subject_filter(subject: str, bind: dict[str, Any]) -> str:
    """The AQL condition on ``dossier`` for a subject: a number, a label or title text.

    ``37035`` matches every dossier of that number, ``37035-XXII`` that one dossier, any other
    text the titles that contain it.
    """
    parsed = parse_dossier_query(subject)
    if parsed is None:
        bind["subject"] = subject
        return "CONTAINS(LOWER(dossier.props.title), LOWER(@subject))"
    number, suffix = parsed
    bind["subject_number"] = number
    if suffix is None:
        return "dossier.props.number == @subject_number"
    bind["subject_suffix"] = suffix
    return (
        "dossier.props.number == @subject_number"
        " AND UPPER(dossier.props.suffix) == @subject_suffix"
    )


def get_dossier_relations(store: ArangoStore, dossier_id: str) -> list[dict[str, Any]]:
    """The ``REVISES``, ``ACCOMPANIES`` and ``RELATED_TO`` edges between this dossier and
    others, with the other dossier and the direction.

    Ordered by relation (``DOSSIER_RELATIONS``), outgoing before incoming, and then by the
    other dossier's number and suffix.
    """
    aql = f"""
    LET outgoing = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @dossier_id AND e.relation IN @relations
            FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
            RETURN {{ edge: e, other: e._to, direction: "outgoing" }}
    )
    LET incoming = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id AND e.relation IN @relations
            FILTER STARTS_WITH(e._from, '{COLLECTION_DOSSIERS}/')
            RETURN {{ edge: e, other: e._from, direction: "incoming" }}
    )
    FOR row IN APPEND(outgoing, incoming)
        LET dossier = DOCUMENT(row.other)
        FILTER dossier != null
        RETURN {{
            relation: row.edge.relation,
            direction: row.direction,
            meta: row.edge.meta,
            dossier: dossier
        }}
    """
    bind = {"dossier_id": dossier_id, "relations": list(DOSSIER_RELATIONS)}
    rows = list(store.query(aql, bind))
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


# The dimensions the dossier lists count as facets: the prop each counts, without a value
# counted as its default. ``status`` is ``open`` or ``closed``.
_DOSSIER_FACETS = {
    "status": 'dossier.props.closed == true ? "closed" : "open"',
    "outcome": "dossier.props.outcome",
    "track": 'dossier.props.track_kind OR "overig"',
    "stage": "dossier.props.current_stage",
    "ministry": "dossier.props.ministry",
}

# The orders of a dossier list; each ends in the key, so a page never repeats a row.
DOSSIER_SORTS = {
    "number": "dossier.props.order ASC",
    "opened_on": "dossier.props.opened_on DESC",
    "closed_on": "dossier.props.closed_on DESC",
    "title": "LOWER(dossier.props.title) ASC",
}


@dataclass(frozen=True)
class DossierFilters:
    """What a dossier list keeps; None keeps everything."""

    status: str | None = None  # open, closed
    outcome: str | None = None
    tracks: tuple[str, ...] | None = None
    stage: str | None = None
    has_stage: tuple[str, ...] | None = None
    ministry: str | None = None
    initiative: bool | None = None
    number: str | None = None  # a prefix of the label: 36264, 37020-
    subject: str | None = None
    committee_slug: str | None = None
    opened_from: str | None = None
    opened_to: str | None = None


def _dossier_filters(
    filters: DossierFilters, bind: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """The AQL conditions on ``dossier``: those that hold for every facet, and those of a
    facet dimension by its name (a facet is counted without its own)."""
    own: dict[str, str] = {}
    shared: list[str] = []
    for name, value, clause in (
        ("status", filters.status, f"({_DOSSIER_FACETS['status']}) == @status"),
        ("outcome", filters.outcome, "dossier.props.outcome == @outcome"),
        ("track", filters.tracks, f"({_DOSSIER_FACETS['track']}) IN @track"),
        ("stage", filters.stage, "dossier.props.current_stage == @stage"),
        ("ministry", filters.ministry, "dossier.props.ministry == @ministry"),
    ):
        if value:
            own[name] = clause
            bind[name] = list(value) if isinstance(value, tuple) else value
    if filters.number:
        # a prefix as a range, so the index on the label answers it
        shared.append(
            "dossier.props.label >= @number AND dossier.props.label < @number_end"
        )
        bind["number"] = filters.number
        bind["number_end"] = filters.number + "\uffff"
    if filters.subject:
        shared.append(_subject_filter(filters.subject, bind))
    if filters.has_stage:
        shared.append("@has_stage ALL IN (dossier.props.stages_present OR [])")
        bind["has_stage"] = list(filters.has_stage)
    if filters.initiative is not None:
        shared.append("dossier.props.initiative == @initiative")
        bind["initiative"] = filters.initiative
    if filters.opened_from:
        shared.append("dossier.props.opened_on >= @opened_from")
        bind["opened_from"] = filters.opened_from
    if filters.opened_to:
        shared.append("dossier.props.opened_on <= @opened_to")
        bind["opened_to"] = filters.opened_to
    if filters.committee_slug:
        shared.append("dossier._id IN committee_dossier_ids")
        bind["committee_slug"] = filters.committee_slug
        bind["led_by"] = RELATION_LED_BY
        bind["about"] = RELATION_ABOUT
    return shared, own


_COMMITTEE_DOSSIERS = f"""
    LET committee = FIRST(
        FOR c IN {COLLECTION_COMMITTEES}
            FILTER c.props.slug == @committee_slug LIMIT 1 RETURN c
    )
    LET committee_dossier_ids = committee != null ? UNIQUE(
        FOR led IN {COLLECTION_EDGES}
            FILTER led._to == committee._id AND led.relation == @led_by
            FOR subject IN {COLLECTION_EDGES}
                FILTER subject._from == led._from AND subject.relation == @about
                FILTER STARTS_WITH(subject._to, '{COLLECTION_DOSSIERS}/')
                RETURN subject._to
    ) : []
"""


def get_dossiers(
    store: ArangoStore,
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

    The committee filter resolves that committee's dossiers once as a set, rather than
    traversing per dossier row.
    """
    bind: dict[str, Any] = {"limit": limit, "offset": offset}
    shared, own = _dossier_filters(filters, bind)

    def where(*clauses: str) -> str:
        return "\n            ".join(f"FILTER {c}" for c in clauses)

    every = where(*shared, *own.values())
    facets = ",\n        ".join(
        f"""{name}: (
            FOR dossier IN {COLLECTION_DOSSIERS}
                {where(*shared, *(c for n, c in own.items() if n != name))}
                COLLECT value = {expression} WITH COUNT INTO n
                SORT n DESC, value
                RETURN {{ value, count: n }}
        )"""
        for name, expression in _DOSSIER_FACETS.items()
    )
    aql = f"""
    {_COMMITTEE_DOSSIERS if filters.committee_slug else ""}
    LET total = LENGTH(
        FOR dossier IN {COLLECTION_DOSSIERS}
            {every}
            RETURN 1
    )
    LET items = (
        FOR dossier IN {COLLECTION_DOSSIERS}
            {every}
            SORT {DOSSIER_SORTS[sort]}, dossier._key
            LIMIT @offset, @limit
            RETURN dossier
    )
    RETURN {{ total: total, items: items, facets: {{
        {facets}
    }} }}
    """
    rows = list(store.query(aql, bind))
    return rows[0] if rows else {"total": 0, "items": [], "facets": {}}


def get_recent_dossiers(
    store: ArangoStore, *, days: int = 30, limit: int = 50, subject: str | None = None
) -> list[dict[str, Any]]:
    """Dossiers with an activity, a vote, a document or their closing in the last *days*
    days, the most recent first.

    A dossier can close without an activity: its law is published in the Staatsblad.
    """
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    bind: dict[str, Any] = {
        "cutoff": cutoff,
        "limit": limit,
        "about": RELATION_ABOUT,
        "part_of": RELATION_PART_OF,
    }
    subject_filter = f"FILTER {_subject_filter(subject, bind)}" if subject else ""
    aql = f"""
    LET by_activity = (
        FOR activity IN {COLLECTION_ACTIVITIES}
            FILTER activity.props.date >= @cutoff
            FOR e IN {COLLECTION_EDGES}
                FILTER e._from == activity._id AND e.relation == @about
                FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
                RETURN {{id: e._to, date: activity.props.date}}
    )
    LET by_decision = (
        FOR decision IN {COLLECTION_DECISIONS}
            FILTER decision.props.date >= @cutoff
            FOR e IN {COLLECTION_EDGES}
                FILTER e._from == decision._id AND e.relation == @about
                FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
                RETURN {{id: e._to, date: decision.props.date}}
    )
    LET by_document = (
        FOR document IN {COLLECTION_DOCUMENTS}
            FILTER document.props.date >= @cutoff
            FOR e IN {COLLECTION_EDGES}
                FILTER e._from == document._id AND e.relation == @part_of
                FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
                RETURN {{id: e._to, date: document.props.date}}
    )
    LET by_closing = (
        FOR dossier IN {COLLECTION_DOSSIERS}
            FILTER dossier.props.closed_on >= @cutoff
            RETURN {{id: dossier._id, date: dossier.props.closed_on}}
    )
    FOR row IN UNION(by_activity, by_decision, by_document, by_closing)
        COLLECT id = row.id AGGREGATE last = MAX(row.date)
        LET dossier = DOCUMENT(id)
        FILTER dossier != null
        {subject_filter}
        SORT last DESC, id
        LIMIT @limit
        RETURN dossier
    """
    return list(store.query(aql, bind))


def get_dossier_number_to_id_map(
    store: ArangoStore, numbers: list[str]
) -> dict[str, str]:
    """Dossier number (``36558``, ``37020-XV``) -> dossier ``_id``, for those that exist."""
    by_key = {make_node_key(number): number for number in numbers}
    existing = store.existing_keys(COLLECTION_DOSSIERS, set(by_key))
    return {
        number: f"{COLLECTION_DOSSIERS}/{key}"
        for key, number in by_key.items()
        if key in existing
    }


def count_dossier_members(store: ArangoStore, dossier_id: str) -> dict[str, int]:
    """How many documents, activities, decisions and commitments a dossier has."""
    aql = f"""
    LET collections = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id
            FILTER e.relation IN [@part_of, @about]
            RETURN SPLIT(e._from, '/')[0]
    )
    RETURN {{
        documents:   LENGTH(FOR c IN collections FILTER c == '{COLLECTION_DOCUMENTS}' RETURN 1),
        activities:  LENGTH(FOR c IN collections FILTER c == '{COLLECTION_ACTIVITIES}' RETURN 1),
        decisions:   LENGTH(FOR c IN collections FILTER c == '{COLLECTION_DECISIONS}' RETURN 1),
        commitments: LENGTH(FOR c IN collections FILTER c == '{COLLECTION_COMMITMENTS}' RETURN 1)
    }}
    """
    bind = {
        "dossier_id": dossier_id,
        "part_of": RELATION_PART_OF,
        "about": RELATION_ABOUT,
    }
    rows = list(store.query(aql, bind))
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
    store: ArangoStore, numbers: Iterable[str]
) -> dict[str, str | None]:
    """Dossier node key -> title, for many dossier numbers in one query."""
    keys = sorted({make_node_key(str(n)) for n in numbers if str(n).strip()})
    if not keys:
        return {}
    aql = f"""
    FOR d IN {COLLECTION_DOSSIERS}
        FILTER d._key IN @keys
        RETURN {{ key: d._key, title: d.props.title }}
    """
    return {row["key"]: row.get("title") for row in store.query(aql, {"keys": keys})}
