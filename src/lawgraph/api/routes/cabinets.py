"""Cabinet endpoints.

GET /api/cabinets              — every cabinet, newest first, with counts
GET /api/cabinets/{key}        — one cabinet with its bewindspersonen by ministry
GET /api/cabinets/{key}/seats  — the seats of its coalition in each Kamer over its period
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.cabinets import (
    CabinetDetailDTO,
    CabinetSeatsResponse,
    CabinetSummaryDTO,
)
from lawgraph.config.constants import COLLECTION_CABINETS
from lawgraph.core.coalition import EK_MAJORITY, TK_MAJORITY
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries.cabinets import get_cabinet, get_cabinets
from lawgraph.db.queries.coalition import cabinet_seats
from lawgraph.db.queries.not_found import require, require_node

router = APIRouter()


@router.get(
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


@router.get(
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
    row = require(get_cabinet(store, key), "Cabinet", key)
    return CabinetDetailDTO.from_detail(row)


@router.get(
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
    cabinet = require_node(store, COLLECTION_CABINETS, key, "Cabinet")
    props = cabinet.get("props") or {}
    seats = cabinet_seats(store, cabinet, dutch_today().isoformat())
    return CabinetSeatsResponse(
        key=cabinet["key"],
        name=props.get("name"),
        from_date=props.get("from_date"),
        to_date=props.get("to_date"),
        majority={"TK": TK_MAJORITY, "EK": EK_MAJORITY},
        tk=seats["tk"],
        ek=seats["ek"],
    )
