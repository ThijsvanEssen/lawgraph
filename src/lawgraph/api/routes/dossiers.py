"""Dossier endpoints.

GET /api/dossiers/open                 — open dossiers, with filters
GET /api/dossiers/recent               — recently active dossiers
GET /api/dossiers/documents/bulk       — documents for several dossiers at once
GET /api/dossiers/{number}             — one dossier with its counts
GET /api/dossiers/{number}/documents   — its documents
GET /api/dossiers/{number}/timeline    — everything that happened, in order
GET /api/dossiers/{number}/mutations   — its pending-change subgraph
GET /api/parties/colors                — party colours for the frontend
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.dossiers import (
    DOSSIER_NUMBER_PATTERN,
    DossierDetailResponse,
    DossierDocumentDTO,
    DossierDocumentsBulkResponse,
    DossierDocumentsResponse,
    DossierListResponse,
    DossierMutationEdge,
    DossierMutationNode,
    DossierMutationsResponse,
    DossierSummaryDTO,
    DossierTimelineResponse,
    timeline_entry,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries.dossiers import (
    count_dossier_members,
    enrich_dossier_docs,
    get_documents_for_dossiers,
    get_dossier_by_number,
    get_dossier_documents,
    get_dossier_hub,
    get_dossier_mutations,
    get_dossier_number_to_id_map,
    get_dossier_timeline,
    get_open_dossiers,
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


def _dossier_or_404(store: ArangoStore, number: str) -> dict[str, Any]:
    dossier = get_dossier_by_number(store, number)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Dossier {number} not found.")
    return dossier


@router.get(
    "/open",
    response_model=DossierListResponse,
    summary="Open dossiers",
    description=(
        "Every dossier that is not closed yet. ``total`` is the absolute "
        "count, independent of ``limit``. Filters on committee slug, subject "
        "text and legislative stage."
    ),
    tags=["dossiers"],
)
def list_open_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    committee: Annotated[str | None, Query(description="Committee slug.")] = None,
    subject: Annotated[
        str | None, Query(description="Substring of the dossier title.")
    ] = None,
    stage: Annotated[
        str | None,
        Query(
            description=(
                "The dossier's latest recognised stage, e.g. 'wetsvoorstel' or "
                "'amendementen'. To filter on a stage being present at all, "
                "use ``has_stage``."
            )
        ),
    ] = None,
    has_stage: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated stages; returns only dossiers that have all "
                "of them, e.g. ``mvt,advies_rvs``."
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DossierListResponse:
    raw = get_open_dossiers(
        store,
        committee_slug=committee,
        subject=subject,
        stage=stage,
        has_stage=(
            [s.strip() for s in has_stage.split(",") if s.strip()]
            if has_stage
            else None
        ),
        limit=limit,
        offset=offset,
    )
    docs = raw.get("items") or []
    enrich_dossier_docs(store, docs)
    return DossierListResponse(
        total=int(raw.get("total") or 0),
        items=[DossierSummaryDTO.from_document(d) for d in docs],
    )


@router.get(
    "/recent",
    response_model=list[DossierSummaryDTO],
    summary="Recently active dossiers",
    description=(
        "Dossiers with an activity, a vote, a document or their closing in the given "
        "period, the most recent first."
    ),
    tags=["dossiers"],
)
def list_recent_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    days: Annotated[int, Query(ge=1, le=365, description="Look-back in days.")] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DossierSummaryDTO]:
    docs = get_recent_dossiers(store, days=days, limit=limit)
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
        "activities, its documents per kind and its Eerste Kamer papers."
    ),
    tags=["dossiers"],
)
def get_dossier(
    number: DossierNumber,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DossierDetailResponse:
    dossier = _dossier_or_404(store, number)
    enrich_dossier_docs(store, [dossier])
    return DossierDetailResponse.from_document(
        dossier,
        counts=count_dossier_members(store, dossier["_id"]),
        hub=get_dossier_hub(store, dossier["_id"]),
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
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DossierTimelineResponse:
    dossier = _dossier_or_404(store, number)
    rows = get_dossier_timeline(
        store,
        dossier["_id"],
        order=order,
        kind_filter=[k.strip() for k in kind.split(",")] if kind else None,
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
