"""Government endpoints: ministries, cabinets and commitments.

GET /api/ministries            — every ministry, in protocol order
GET /api/cabinets              — every cabinet, newest first, with counts
GET /api/cabinets/{key}        — one cabinet with its bewindspersonen by ministry
GET /api/commitments           — commitments, filtered and paged
GET /api/commitments/{key}     — one commitment
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.government import (
    CabinetDetailDTO,
    CabinetSummaryDTO,
    CommitmentDTO,
    CommitmentFacetsDTO,
    CommitmentListResponse,
    CommitmentStatus,
    MinistryDTO,
)
from lawgraph.core.ministries import MINISTRIES
from lawgraph.db import ArangoStore
from lawgraph.db.queries.cabinets import (
    get_cabinet,
    get_cabinets,
    get_commitment,
    get_commitments,
)

ministries_router = APIRouter()
cabinets_router = APIRouter()
commitments_router = APIRouter()


@ministries_router.get(
    "",
    response_model=list[MinistryDTO],
    summary="Ministries",
    description=(
        "Every ministry a post, a dossier or a commitment can name, in protocol order; a "
        "former ministry (``Verkeer en Waterstaat``) follows its successor and names it."
    ),
    tags=["government"],
)
def list_ministries() -> list[MinistryDTO]:
    return [
        MinistryDTO(
            key=MinistryKey(m.key),
            name=m.name,
            successor=MinistryKey(m.successor) if m.successor else None,
            until=m.until,
        )
        for m in MINISTRIES
    ]


@cabinets_router.get(
    "",
    response_model=list[CabinetSummaryDTO],
    summary="Cabinets",
    description=(
        "Every Dutch cabinet, newest first: those since 1945 from Rijksoverheid, with "
        "their prime minister, parties, ``phases`` and ``demissionary_from``; those "
        "before from Wikidata (name and period only). Counts: ``members`` "
        "(bewindspersonen), ``bills`` (government bills brought in while it was in "
        "office) and ``commitments``."
    ),
    tags=["government"],
)
def list_cabinets(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[CabinetSummaryDTO]:
    return [CabinetSummaryDTO.from_row(row) for row in get_cabinets(store)]


@cabinets_router.get(
    "/{key}",
    response_model=CabinetDetailDTO,
    summary="Cabinet detail",
    description=(
        "One cabinet with its bewindspersonen grouped by ministry (protocol order, the "
        "minister-president first) and within it by seat (minister, ministers without "
        "portfolio, staatssecretarissen), the posts of a seat in order of start: a "
        "successor is the next post, a stand-in has ``acting``. Each post with the "
        "person's counts within the cabinet: ``dossiers`` and ``bills`` they signed as "
        "bewindspersoon, and ``open_commitments``."
    ),
    tags=["government"],
)
def get_cabinet_detail(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> CabinetDetailDTO:
    row = get_cabinet(store, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Cabinet '{key}' not found.")
    return CabinetDetailDTO.from_detail(row)


@commitments_router.get(
    "",
    response_model=CommitmentListResponse,
    summary="Commitments",
    description=(
        "Commitments (toezeggingen) of bewindspersonen, paged; ``total`` counts every "
        "match. ``overdue`` keeps the open ones whose expected date has passed. "
        "``facets`` counts per ``status``, ``cabinet`` and ``ministry`` the commitments "
        "under the other filters."
    ),
    tags=["government"],
)
def list_commitments(
    store: Annotated[ArangoStore, Depends(get_store)],
    status: Annotated[CommitmentStatus | None, Query()] = None,
    member: Annotated[str | None, Query(description="Member key.")] = None,
    cabinet: Annotated[str | None, Query(description="Cabinet key.")] = None,
    ministry: Annotated[MinistryKey | None, Query()] = None,
    dossier: Annotated[
        str | None, Query(description="A dossier number or label: 36600, 36600-VII.")
    ] = None,
    due_before: Annotated[
        dt.date | None, Query(description="Expected before this day.")
    ] = None,
    overdue: Annotated[bool, Query()] = False,
    q: Annotated[str | None, Query(description="Words of the text.")] = None,
    sort: Annotated[
        Literal["date", "expected_resolution"],
        Query(description="Newest made first, or soonest due first."),
    ] = "date",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CommitmentListResponse:
    raw = get_commitments(
        store,
        status=status,
        member=member,
        cabinet=cabinet,
        ministry=ministry.value if ministry else None,
        dossier=dossier,
        due_before=due_before.isoformat() if due_before else None,
        overdue=overdue,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return CommitmentListResponse(
        total=int(raw.get("total") or 0),
        items=[CommitmentDTO.from_row(row) for row in raw.get("items") or []],
        facets=CommitmentFacetsDTO(**(raw.get("facets") or {})),
    )


@commitments_router.get(
    "/{key}",
    response_model=CommitmentDTO,
    summary="Commitment detail",
    tags=["government"],
)
def get_commitment_detail(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> CommitmentDTO:
    row = get_commitment(store, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Commitment '{key}' not found.")
    return CommitmentDTO.from_row(row)
