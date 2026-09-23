"""Semantic relationship endpoints: the types and a search of the classified relationships."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.relationships import (
    RelationshipDTO,
    RelationshipSearchResponse,
)
from lawgraph.config.constants import SEMANTIC_RELATIONSHIP_TYPES
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore
from lawgraph.db.queries.relationships import search_relationships

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/types",
    summary="Available semantic relationship types",
    description="The supported semantic relationship types.",
    tags=["relationships"],
)
def get_relationship_types() -> dict[str, list[str]]:
    return {"semantic_types": sorted(SEMANTIC_RELATIONSHIP_TYPES)}


@router.get(
    "/search",
    response_model=RelationshipSearchResponse,
    summary="Search semantic relationships",
    description=(
        "Searches the classified article relationships, optionally filtered by "
        "semantic type and/or law (the bwb_id of the source article)."
    ),
    tags=["relationships"],
)
def search(
    store: Annotated[ArangoStore, Depends(get_store)],
    type: Annotated[str | None, Query(alias="type")] = None,
    law: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RelationshipSearchResponse:
    if type is not None and type not in SEMANTIC_RELATIONSHIP_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown semantic type {type!r}. "
            f"Valid types: {sorted(SEMANTIC_RELATIONSHIP_TYPES)}",
        )
    rows, total = search_relationships(
        store, semantic_type=type, bwb_id=law, limit=limit, offset=offset
    )
    relationships = [
        RelationshipDTO.from_edge(
            row["edge"],
            source_article=row.get("source_article"),
            target=row.get("target"),
        )
        for row in rows
    ]
    return RelationshipSearchResponse(
        relationships=relationships, total=total, limit=limit, offset=offset
    )
