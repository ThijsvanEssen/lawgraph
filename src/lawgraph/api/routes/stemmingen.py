"""Stemmingen endpoints — vote browser for the parliamentary data."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_stemming_detail,
    get_stemming_publication,
    get_stemmingen,
)
from lawgraph.api.schemas import (
    PartijStemDTO,
    PublicationTextResponse,
    StemmingDTO,
    StemmingListResponse,
    StemmingSummaryItemDTO,
)
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    response_model=StemmingListResponse,
    summary="Stemmingen browser",
    description=(
        "Geeft een gepagineerde lijst van stemmingen (één per Besluit), "
        "optioneel gefilterd op aangenomen-status of partij. "
        "Sorteert op datum aflopend. ``total`` is het absolute aantal "
        "(onafhankelijk van ``limit``)."
    ),
    tags=["stemmingen"],
)
def list_stemmingen(
    store: Annotated[ArangoStore, Depends(get_store)],
    aangenomen: bool | None = Query(
        default=None, description="Filter op aangenomen (true/false)"
    ),
    partij: str | None = Query(
        default=None, description="Filter op partijnaam (voor of tegen)"
    ),
    chamber: str | None = Query(
        default=None, description="Filter op kamer: 'TK' of 'EK'"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> StemmingListResponse:
    raw = get_stemmingen(
        store,
        aangenomen=aangenomen,
        partij=partij,
        chamber=chamber,
        limit=limit,
        offset=offset,
    )
    return StemmingListResponse(
        total=int(raw.get("total") or 0),
        items=[StemmingSummaryItemDTO(**row) for row in raw.get("items") or []],
    )


@router.get(
    "/{key}",
    response_model=StemmingDTO,
    summary="Stemming detail",
    description=(
        "Haalt één stemming op met volledige voor/tegen/onthouding "
        "breakdown per fractie."
    ),
    tags=["stemmingen"],
)
def get_stemming(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> StemmingDTO:
    doc = get_stemming_detail(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Stemming '{key}' not found.")
    # get_stemming_detail returns a flat AQL row (already projected), not
    # a raw Arango doc with nested props — build the DTO from the row
    # directly instead of going through StemmingDTO.from_document.
    return StemmingDTO(
        id=doc["id"],
        key=doc["key"],
        datum=doc.get("datum"),
        onderwerp=doc.get("onderwerp"),
        besluit_id=doc.get("besluit_id"),
        aangenomen=bool(doc.get("aangenomen")),
        chamber=doc.get("chamber"),
        voor=[
            PartijStemDTO(**v) for v in (doc.get("voor") or []) if isinstance(v, dict)
        ],
        tegen=[
            PartijStemDTO(**v) for v in (doc.get("tegen") or []) if isinstance(v, dict)
        ],
        onthouding=[
            PartijStemDTO(**v)
            for v in (doc.get("onthouding") or [])
            if isinstance(v, dict)
        ],
    )


@router.get(
    "/{key}/publication",
    response_model=PublicationTextResponse,
    summary="Publicatie achter een stemming",
    description=(
        "Resolveert het kamerstuk (motie, amendement of wetsvoorstel) "
        "waar deze stemming over ging, inclusief volledige tekst."
    ),
    tags=["stemmingen"],
)
def get_stemming_publication_route(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> PublicationTextResponse:
    stemming = get_stemming_detail(store, key)
    if stemming is None:
        raise HTTPException(status_code=404, detail=f"Stemming '{key}' not found.")
    pub = get_stemming_publication(store, key)
    if pub is None:
        raise HTTPException(
            status_code=404,
            detail=f"No publication resolvable for stemming '{key}'.",
        )
    return PublicationTextResponse.from_document(pub)
