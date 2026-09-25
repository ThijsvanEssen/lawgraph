"""Dossier endpoints.

GET /api/dossiers                      — every dossier, with filters, order and facets
GET /api/dossiers/open                 — the same with status=open
GET /api/dossiers/recent               — recently active dossiers
GET /api/dossiers/documents/bulk       — documents for several dossiers at once
GET /api/dossiers/{number}             — one dossier with its counts
GET /api/dossiers/{number}/documents   — its documents
GET /api/dossiers/{number}/timeline    — everything that happened, in order
GET /api/dossiers/{number}/mutations   — its pending-change subgraph
GET /api/parties/colors                — party colours for the frontend
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Annotated, Any, Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import MinistryKey, parse_choices
from lawgraph.api.schemas.dossiers import (
    DOSSIER_NUMBER_PATTERN,
    DossierDetailResponse,
    DossierDocumentDTO,
    DossierDocumentsBulkResponse,
    DossierDocumentsResponse,
    DossierFacetsDTO,
    DossierListResponse,
    DossierMutationEdge,
    DossierMutationNode,
    DossierMutationsResponse,
    DossierOutcome,
    DossierStage,
    DossierSummaryDTO,
    DossierTimelineResponse,
    DossierTrack,
    timeline_entry,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries.dossiers import (
    DossierFilters,
    count_dossier_members,
    enrich_dossier_docs,
    get_documents_for_dossiers,
    get_dossier_by_number,
    get_dossier_documents,
    get_dossier_hub,
    get_dossier_mutations,
    get_dossier_number_to_id_map,
    get_dossier_relations,
    get_dossier_timeline,
    get_dossiers,
    get_recent_dossiers,
)

router = APIRouter()

DossierNumber = Annotated[
    str,
    Path(
        description="Dossier number, e.g. 29684, 29684-I, 21501-31 or 36956-(R2220).",
        pattern=DOSSIER_NUMBER_PATTERN,
    ),
]


# What the dossier lists filter on: a number, a dossier, or words of the title.
Subject = Annotated[
    str | None,
    Query(
        description=(
            "A number (``37035``: every dossier of that number), a dossier (``37035-XXII``) "
            "or a substring of the title."
        )
    ),
]


def _dossier_or_404(store: ArangoStore, number: str) -> dict[str, Any]:
    dossier = get_dossier_by_number(store, number)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Dossier {number} not found.")
    return dossier


class _ListParams:
    """The filters, order and page of a dossier list, as query parameters."""

    def __init__(
        self,
        status: Annotated[
            Literal["open", "closed", "all"],
            Query(description="Open dossiers, closed ones (with an outcome) or both."),
        ] = "all",
        outcome: Annotated[DossierOutcome | None, Query()] = None,
        track: Annotated[
            str | None,
            Query(
                description="Comma-separated tracks, e.g. ``wetsvoorstel,begroting``."
            ),
        ] = None,
        number: Annotated[
            str | None,
            Query(
                description="The start of the number: ``36264`` (that number and its "
                "chapters), ``37020-`` (the chapters of 37020).",
                pattern=r"^\d+(-[A-Za-z0-9()]*)?$",
            ),
        ] = None,
        committee: Annotated[str | None, Query(description="Committee slug.")] = None,
        subject: Subject = None,
        stage: Annotated[
            DossierStage | None,
            Query(
                description="The dossier's latest recognised stage. To filter on a stage "
                "being present at all, use ``has_stage``."
            ),
        ] = None,
        has_stage: Annotated[
            str | None,
            Query(
                description="Comma-separated stages; only dossiers that have all of them, "
                "e.g. ``mvt,advies_rvs``."
            ),
        ] = None,
        ministry: Annotated[
            MinistryKey | None, Query(description="The ministry that brought it in.")
        ] = None,
        initiative: Annotated[
            bool | None,
            Query(
                description="True: brought in by a Kamerlid; false: by the government."
            ),
        ] = None,
        opened_from: Annotated[
            dt.date | None, Query(description="Opened on or after this day.")
        ] = None,
        opened_to: Annotated[
            dt.date | None, Query(description="Opened on or before this day.")
        ] = None,
        sort: Annotated[
            Literal["number", "opened_on", "closed_on", "title"] | None,
            Query(
                description="``number`` in the order of the Kamer, ``opened_on`` and "
                "``closed_on`` newest first, ``title`` alphabetically; ties by key. "
                "Default ``number`` with a ``number`` filter, else ``opened_on``."
            ),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.filters = DossierFilters(
            status=None if status == "all" else status,
            outcome=outcome,
            tracks=parse_choices(track, get_args(DossierTrack), "track"),
            stage=stage,
            has_stage=parse_choices(has_stage, get_args(DossierStage), "has_stage"),
            ministry=ministry.value if ministry else None,
            initiative=initiative,
            number=number,
            subject=subject,
            committee_slug=committee,
            opened_from=opened_from.isoformat() if opened_from else None,
            opened_to=opened_to.isoformat() if opened_to else None,
        )
        self.sort = sort or ("number" if number else "opened_on")
        self.limit = limit
        self.offset = offset


def _list(store: ArangoStore, params: _ListParams) -> DossierListResponse:
    raw = get_dossiers(
        store,
        params.filters,
        sort=params.sort,
        limit=params.limit,
        offset=params.offset,
    )
    docs = raw.get("items") or []
    enrich_dossier_docs(store, docs)
    return DossierListResponse(
        total=int(raw.get("total") or 0),
        items=[DossierSummaryDTO.from_document(d) for d in docs],
        facets=DossierFacetsDTO(**raw.get("facets") or {}),
    )


_LIST_DESCRIPTION = (
    "``total`` is the absolute count, independent of ``limit``. ``facets`` counts the "
    "dossiers per status, outcome, track, current stage and ministry under the other "
    "filters, each dimension without its own filter."
)


@router.get(
    "",
    response_model=DossierListResponse,
    summary="Dossiers",
    description=(
        "Every dossier, open and closed, filtered by status, outcome, track, the start of "
        "its number, committee, subject (a number, a dossier, or words of the title, such "
        "as its short title), stage, ministry, initiative and the day it opened. "
        + _LIST_DESCRIPTION
    ),
    tags=["dossiers"],
)
def list_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    params: Annotated[_ListParams, Depends()],
) -> DossierListResponse:
    return _list(store, params)


@router.get(
    "/open",
    response_model=DossierListResponse,
    summary="Open dossiers",
    description=(
        "``GET /api/dossiers`` with ``status=open``: the dossiers not closed yet. "
        + _LIST_DESCRIPTION
    ),
    tags=["dossiers"],
)
def list_open_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    params: Annotated[_ListParams, Depends()],
) -> DossierListResponse:
    params.filters = replace(params.filters, status="open")
    return _list(store, params)


@router.get(
    "/recent",
    response_model=list[DossierSummaryDTO],
    summary="Recently active dossiers",
    description=(
        "Dossiers with an activity, a vote, a document or their closing in the given "
        "period, the most recent first. ``subject`` narrows them to a number, a dossier "
        "or title text."
    ),
    tags=["dossiers"],
)
def list_recent_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    days: Annotated[int, Query(ge=1, le=365, description="Look-back in days.")] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    subject: Subject = None,
) -> list[DossierSummaryDTO]:
    docs = get_recent_dossiers(store, days=days, limit=limit, subject=subject)
    enrich_dossier_docs(store, docs)
    return [DossierSummaryDTO.from_document(d) for d in docs]


@router.get(
    "/documents/bulk",
    response_model=DossierDocumentsBulkResponse,
    summary="Documents for several dossiers",
    description=(
        "The top documents per dossier for a list of dossier numbers, in one "
        "call rather than one per dossier."
    ),
    tags=["dossiers"],
)
def list_documents_for_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    numbers: Annotated[
        str,
        Query(
            description="Comma-separated dossier numbers, e.g. '29684,29515-Z'.",
            min_length=1,
        ),
    ],
    per_dossier_limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> DossierDocumentsBulkResponse:
    wanted = [n.strip() for n in numbers.split(",") if n.strip()]
    number_to_id = get_dossier_number_to_id_map(store, wanted) if wanted else {}
    if not number_to_id:
        return DossierDocumentsBulkResponse(items={})
    by_id = get_documents_for_dossiers(
        store, list(number_to_id.values()), per_dossier_limit=per_dossier_limit
    )
    return DossierDocumentsBulkResponse(
        items={
            number: [DossierDocumentDTO.from_row(d) for d in by_id.get(dossier_id, [])]
            for number, dossier_id in number_to_id.items()
        }
    )


@router.get(
    "/{number}",
    response_model=DossierDetailResponse,
    summary="Dossier detail",
    description=(
        "One dossier: its title, stage, how many documents, activities, "
        "decisions and commitments it holds, and what it links to: the "
        "instruments it legislated, amends, introduces or repeals (one item per "
        "instrument, relation and status), the committees that lead its "
        "activities, its documents per kind, its Eerste Kamer papers, and the dossiers it "
        "revises, accompanies or is related to (and those that revise, accompany or "
        "relate to it)."
    ),
    tags=["dossiers"],
)
def get_dossier(
    number: DossierNumber,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DossierDetailResponse:
    dossier = _dossier_or_404(store, number)
    enrich_dossier_docs(store, [dossier])
    relations = get_dossier_relations(store, dossier["_id"])
    enrich_dossier_docs(store, [row["dossier"] for row in relations])
    return DossierDetailResponse.from_document(
        dossier,
        counts=count_dossier_members(store, dossier["_id"]),
        hub=get_dossier_hub(store, dossier["_id"]),
        relations=relations,
    )


@router.get(
    "/{number}/documents",
    response_model=DossierDocumentsResponse,
    summary="Dossier documents",
    description=(
        "The documents in this dossier — linked directly or through a case — "
        "newest first. ``total`` is the absolute count."
    ),
    tags=["dossiers"],
)
def list_dossier_documents(
    number: DossierNumber,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DossierDocumentsResponse:
    dossier = _dossier_or_404(store, number)
    raw = get_dossier_documents(store, dossier["_id"], limit=limit, offset=offset)
    return DossierDocumentsResponse(
        total=int(raw.get("total") or 0),
        items=[DossierDocumentDTO.from_row(d) for d in raw.get("items") or []],
    )


@router.get(
    "/{number}/timeline",
    response_model=DossierTimelineResponse,
    summary="Dossier timeline",
    description=(
        "Documents, activities, decisions and commitments in date order, "
        "newest first by default. Filter with ``?kind=motie,amendement``."
    ),
    tags=["dossiers"],
)
def get_timeline(
    number: DossierNumber,
    store: Annotated[ArangoStore, Depends(get_store)],
    order: Annotated[Literal["asc", "desc"], Query(description="Date order.")] = "desc",
    kind: Annotated[
        str | None, Query(description="Comma-separated document kinds.")
    ] = None,
    include_planned: Annotated[
        bool,
        Query(description="False leaves out the activities with status ``Gepland``."),
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DossierTimelineResponse:
    dossier = _dossier_or_404(store, number)
    rows = get_dossier_timeline(
        store,
        dossier["_id"],
        order=order,
        kind_filter=[k.strip() for k in kind.split(",")] if kind else None,
        include_planned=include_planned,
        limit=limit,
    )
    entries = [timeline_entry(row) for row in rows]
    return DossierTimelineResponse(
        number=number, total=len(entries), order=order, entries=entries
    )


@router.get(
    "/{number}/mutations",
    response_model=DossierMutationsResponse,
    summary="Dossier mutation graph",
    description=(
        "The nodes and edges by which this dossier proposes to change the "
        "law, shaped like the graph endpoint so the frontend can render it "
        "directly."
    ),
    tags=["dossiers"],
)
def get_mutations(
    number: DossierNumber,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DossierMutationsResponse:
    dossier = _dossier_or_404(store, number)
    raw = get_dossier_mutations(store, dossier["_id"])
    return DossierMutationsResponse(
        number=number,
        nodes=[DossierMutationNode.from_document(n) for n in raw.get("nodes", [])],
        edges=[
            DossierMutationEdge(
                from_id=e.get("from_id"),
                to_id=e.get("to_id"),
                relation=e.get("relation"),
                status=e.get("status"),
                meta=e.get("meta"),
                kind=e.get("kind", "mutation"),
            )
            for e in raw.get("edges", [])
        ],
    )
