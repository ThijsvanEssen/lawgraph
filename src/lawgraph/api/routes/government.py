"""Government endpoints: ministries, cabinets and commitments.

GET /api/ministries            — every ministry, in protocol order
GET /api/cabinets              — every cabinet, newest first, with counts
GET /api/cabinets/{key}        — one cabinet with its bewindspersonen by ministry
GET /api/cabinets/{key}/seats  — the seats of its coalition in each Kamer over its period
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
    CabinetSeatsResponse,
    CabinetSummaryDTO,
    CommitmentDTO,
    CommitmentFacetsDTO,
    CommitmentListResponse,
    MinistryDTO,
    MinistryPeriodDTO,
)
from lawgraph.config.constants import COLLECTION_CABINETS
from lawgraph.core.coalition import EK_MAJORITY, TK_MAJORITY
from lawgraph.core.ministries import MINISTRIES
from lawgraph.db import GraphStore
from lawgraph.db.queries.cabinets import (
    get_cabinet,
    get_cabinets,
    get_commitment,
    get_commitments,
)
from lawgraph.db.queries.coalition import cabinet_seats

ministries_router = APIRouter()
cabinets_router = APIRouter()
commitments_router = APIRouter()


@ministries_router.get(
    "",
    response_model=list[MinistryDTO],
    summary="Ministries",
    description=(
        "Every ministry a post, a dossier or a commitment can name, in protocol order; a "
        "former ministry (``Verkeer en Waterstaat``) follows its successor and names it. "
        "From ``data/ministries.json``: TOOI since about 2010 (with the decree of each "
        "change), the Rijksoverheid cabinet pages before; ``periods`` say which."
    ),
    tags=["government"],
)
def list_ministries() -> list[MinistryDTO]:
    return [
        MinistryDTO(
            key=MinistryKey(m.key),
            name=m.name,
            abbreviation=m.abbreviation,
            tooi=m.tooi,
            successor=MinistryKey(m.successor) if m.successor else None,
            until=m.until,
            periods=[
                MinistryPeriodDTO(
                    from_date=p.from_date,
                    until=p.until,
                    successor=MinistryKey(p.successor) if p.successor else None,
                    basis=p.basis,
                    source=p.source,
                    successor_source=p.successor_source,
                )
                for p in m.periods
            ],
        )
        for m in MINISTRIES
    ]


@cabinets_router.get(
    "",
    response_model=list[CabinetSummaryDTO],
    summary="Cabinets",
    description=(
        "Every Dutch cabinet since 1945, newest first, from Rijksoverheid: with its "
        "prime minister, parties, ``phases`` and ``demissionary_from``. Counts: "
        "``members`` (bewindspersonen), ``bills`` (government bills brought in while it "
        "was in office) and ``commitments``."
    ),
    tags=["government"],
)
def list_cabinets(
    store: Annotated[GraphStore, Depends(get_store)],
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
    store: Annotated[GraphStore, Depends(get_store)],
) -> CabinetDetailDTO:
    row = get_cabinet(store, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Cabinet '{key}' not found.")
    return CabinetDetailDTO.from_detail(row)


@cabinets_router.get(
    "/{key}/seats",
    response_model=CabinetSeatsResponse,
    summary="Cabinet seats",
    description=(
        "The seats of the cabinet's coalition in each Kamer over its period, a stretch per "
        "change. The coalition on a day is the factions whose party held a post in the "
        "cabinet that day (Rijksoverheid): a party that leaves the cabinet leaves the "
        "coalition, a faction that splits off a coalition party is opposition. The seats "
        "are those the members held (FractieZetelPersoon)."
    ),
    tags=["government"],
)
def get_cabinet_seats(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> CabinetSeatsResponse:
    # the cabinet node alone: its detail counts every paper its members signed
    cabinet = store.get_document(COLLECTION_CABINETS, key)
    if cabinet is None:
        raise HTTPException(status_code=404, detail=f"Cabinet '{key}' not found.")
    props = cabinet.get("props") or {}
    seats = cabinet_seats(store, cabinet, dt.date.today().isoformat())
    return CabinetSeatsResponse(
        key=cabinet["_key"],
        name=props.get("name"),
        from_date=props.get("from_date"),
        to_date=props.get("to_date"),
        majority={"TK": TK_MAJORITY, "EK": EK_MAJORITY},
        tk=seats["tk"],
        ek=seats["ek"],
    )


@commitments_router.get(
    "",
    response_model=CommitmentListResponse,
    summary="Commitments",
    description=(
        "Commitments (toezeggingen) of bewindspersonen, paged; ``total`` counts every "
        "match. ``status`` is the Toezegging.Status of the Tweede Kamer (`Openstaand`, "
        "`Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Deels Afgedaan`, `Vervallen`). "
        "``overdue`` keeps the `Openstaand` ones whose expected date has passed. "
        "``facets`` counts per ``status``, ``cabinet`` and ``ministry`` the commitments "
        "under the other filters."
    ),
    tags=["government"],
)
def list_commitments(
    store: Annotated[GraphStore, Depends(get_store)],
    status: Annotated[
        str | None,
        Query(
            description="A Toezegging.Status as the Tweede Kamer writes it: `Openstaand`."
        ),
    ] = None,
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
    date_from: Annotated[
        dt.date | None,
        Query(alias="from", description="Made on or after this day, YYYY-MM-DD."),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Made on or before this day, YYYY-MM-DD."),
    ] = None,
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
        made_from=date_from.isoformat() if date_from else None,
        made_to=date_to.isoformat() if date_to else None,
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
    store: Annotated[GraphStore, Depends(get_store)],
) -> CommitmentDTO:
    row = get_commitment(store, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Commitment '{key}' not found.")
    return CommitmentDTO.from_row(row)
