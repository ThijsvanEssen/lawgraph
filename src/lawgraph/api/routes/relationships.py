"""Semantic relationship endpoints: the types and a search of the classified relationships."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import parse_choices
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
        "semantic type and/or law (the bwb_id of the source article). ``type`` keeps "
        "the relationships of any of the types it names, ``exclude_type`` drops those "
        "of the types it names (both comma-separated): ``exclude_type=cross_reference`` "
        "gives every other kind in one call."
    ),
    tags=["relationships"],
)
def search(
    store: Annotated[ArangoStore, Depends(get_store)],
    type: Annotated[
        str | None,
        Query(
            alias="type",
            description="Semantic types to keep, comma-separated.",
            examples=["definitional_reference,scope_limitation"],
        ),
    ] = None,
    exclude_type: Annotated[
        str | None,
        Query(
            description="Semantic types to leave out, comma-separated.",
            examples=["cross_reference"],
        ),
    ] = None,
    law: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RelationshipSearchResponse:
    rows, total = search_relationships(
        store,
        semantic_types=parse_choices(type, SEMANTIC_RELATIONSHIP_TYPES, "type"),
        exclude_types=parse_choices(
            exclude_type, SEMANTIC_RELATIONSHIP_TYPES, "exclude_type"
        ),
        bwb_id=law,
        limit=limit,
        offset=offset,
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
