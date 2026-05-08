"""Stemmingen endpoints — vote browser for the parliamentary data."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_stemming_detail, get_stemmingen
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    summary="Stemmingen browser",
    description=(
        "Geeft een gepagineerde lijst van stemmingen (één per Besluit), "
        "optioneel gefilterd op aangenomen-status of partij. "
        "Sorteert op datum aflopend."
    ),
    tags=["stemmingen"],
)
async def list_stemmingen(
    store: Annotated[ArangoStore, Depends(get_store)],
    aangenomen: bool | None = Query(
        default=None, description="Filter op aangenomen (true/false)"
    ),
    partij: str | None = Query(
        default=None, description="Filter op partijnaam (voor of tegen)"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Return a paginated list of stemmingen, newest first."""
    return get_stemmingen(
        store,
        aangenomen=aangenomen,
        partij=partij,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{key}",
    summary="Stemming detail",
    description="Haalt één stemming op met volledige voor/tegen/onthouding breakdown.",
    tags=["stemmingen"],
)
async def get_stemming(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> dict:
    """Return a single stemming by its document key."""
    doc = get_stemming_detail(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Stemming '{key}' niet gevonden.")
    return doc
