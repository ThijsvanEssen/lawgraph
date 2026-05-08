"""API routes for parliamentary committees and members.

GET /api/commissies                       — list all committees with active dossier counts
GET /api/commissies/{slug}                — committee detail with members and recent activiteiten
GET /api/leden/{key}                      — member detail
GET /api/leden/{key}/votes                — paginated voting record
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_all_commissies,
    get_commissie_by_slug,
    get_lid_votes,
)
from lawgraph.api.schemas import CommissieDTO, LidDTO
from lawgraph.db import ArangoStore

router = APIRouter()
leden_router = APIRouter()


@router.get(
    "",
    response_model=list[CommissieDTO],
    summary="Alle commissies",
    description="Geeft alle parlementaire commissies met het aantal actieve dossiers.",
    tags=["commissies"],
)
def list_commissies(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[CommissieDTO]:
    docs = get_all_commissies(store)
    return [
        CommissieDTO.from_document(
            d, active_dossier_count=d.get("active_dossier_count", 0)
        )
        for d in docs
    ]


@router.get(
    "/{slug}",
    response_model=CommissieDTO,
    summary="Commissie detail",
    description="Detail van één commissie, inclusief leden en recente activiteiten.",
    tags=["commissies"],
)
def get_commissie(
    slug: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> CommissieDTO:
    doc = get_commissie_by_slug(store, slug)
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"Commissie '{slug}' niet gevonden."
        )
    return CommissieDTO.from_document(doc)


@leden_router.get(
    "/{key}",
    response_model=LidDTO,
    summary="Lid detail",
    description="Geeft de basisgegevens van een Kamerlid of minister.",
    tags=["leden"],
)
def get_lid(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> LidDTO:
    node = store.get_node("leden", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Lid '{key}' niet gevonden.")
    doc = {
        "_id": node.id,
        "_key": node.key,
        "type": node.type.value,
        "labels": node.labels,
        "props": node.props,
    }
    return LidDTO.from_document(doc)


@leden_router.get(
    "/{key}/votes",
    summary="Stemmingsgeschiedenis van een lid",
    description="Gepagineerd stemoverzicht van een Kamerlid op basis van partij.",
    tags=["leden"],
)
def get_lid_voting_record(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    node = store.get_node("leden", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Lid '{key}' niet gevonden.")
    lid_id = node.id
    votes = get_lid_votes(store, lid_id or "", limit=limit)
    return {"lid_id": lid_id, "votes": votes, "total": len(votes)}
