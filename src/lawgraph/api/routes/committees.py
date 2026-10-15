"""Committee endpoints.

GET /api/committees                    — every committee
GET /api/committees/{slug}             — one committee in full
GET /api/committees/{slug}/activities  — the activities it leads
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import (
    LIST_MAX,
    ActiveFrom,
    ActiveTo,
    ListChamber,
    ListLimit,
)
from lawgraph.api.schemas.committees import (
    CommitteeActivitiesResponse,
    CommitteeActivityDTO,
    CommitteeDetailDTO,
    CommitteeDTO,
)
from lawgraph.api.schemas.common import dossier_names_of
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.committees import (
    get_committee_activities,
    get_committee_detail,
    get_committees,
)
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.not_found import require

router = APIRouter()


@router.get(
    "",
    response_model=list[CommitteeDTO],
    summary="All committees",
    description="Every parliamentary committee with its number of open dossiers.",
    tags=["committees"],
)
def list_committees(
    store: Annotated[GraphStore, Depends(get_store)],
    chamber: ListChamber = "TK",
    active_from: ActiveFrom = None,
    active_to: ActiveTo = None,
) -> list[CommitteeDTO]:
    return [
        CommitteeDTO.from_document(doc)
        for doc in get_committees(
            store,
            chamber=chamber,
            active_from=iso_day(active_from),
            active_to=iso_day(active_to),
        )
    ]


@router.get(
    "/{slug}",
    response_model=CommitteeDetailDTO,
    summary="Committee detail",
    description=(
        "One committee with its members and a page of the dossiers it leads, "
        "newest first; ``dossier_total`` is the absolute count. By default "
        "only current members are returned — a seat with no end date, or an "
        "end date still ahead. Pass ``?current_only=false`` for every member "
        "the committee ever had. ``limit``, ``offset`` and ``status`` page and "
        "filter the dossiers."
    ),
    tags=["committees"],
)
def get_committee(
    slug: str,
    store: Annotated[GraphStore, Depends(get_store)],
    current_only: Annotated[
        bool, Query(description="Only members currently seated on this committee.")
    ] = True,
    status: Annotated[
        Literal["open", "closed"] | None,
        Query(description="Only the open or only the closed dossiers."),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=LIST_MAX, description="Dossiers per page.")
    ] = 100,
    offset: Annotated[int, Query(ge=0, description="Dossiers to skip.")] = 0,
) -> CommitteeDetailDTO:
    doc = require(
        get_committee_detail(
            store,
            slug,
            current_only=current_only,
            status=status,
            limit=limit,
            offset=offset,
        ),
        "Committee",
        slug,
    )
    return CommitteeDetailDTO.from_detail_document(doc)


@router.get(
    "/{slug}/activities",
    response_model=CommitteeActivitiesResponse,
    summary="Committee activities",
    description=(
        "The activities (debates, hearings) a committee leads, newest first, "
        "with the dossiers on their agenda. ``total`` is the absolute count."
    ),
    tags=["committees"],
)
def list_committee_activities(
    slug: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: ListLimit = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CommitteeActivitiesResponse:
    raw = require(
        get_committee_activities(store, slug, limit=limit, offset=offset),
        "Committee",
        slug,
    )
    names = load_dossier_names(store)
    return CommitteeActivitiesResponse(
        total=int(raw.get("total") or 0),
        items=[
            CommitteeActivityDTO(
                **item,
                dossiers=dossier_names_of(item.get("dossier_numbers") or [], names),
            )
            for item in raw.get("items") or []
        ],
    )
