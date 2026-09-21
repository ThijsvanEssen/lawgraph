"""Semantic relationship endpoints — search, curation tagging, community voting."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import (
    get_store,
    require_curation_key,
    require_write_key,
)
from lawgraph.api.queries.relationships import (
    resolve_article_id,
    search_relationships,
    tag_relationship,
    vote_relationship,
)
from lawgraph.api.schemas.common import CommunityVotes
from lawgraph.api.schemas.relationships import (
    RelationshipDTO,
    RelationshipSearchResponse,
    RelationshipTagRequest,
    RelationshipVoteRequest,
    RelationshipVoteResponse,
)
from lawgraph.config.constants import SEMANTIC_RELATIONSHIP_TYPES, SEMANTIC_SOURCES
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/types",
    summary="Available semantic relationship types",
    description="The supported semantic relationship types and source values.",
    tags=["relationships"],
)
def get_relationship_types() -> dict[str, list[str]]:
    return {
        "semantic_types": sorted(SEMANTIC_RELATIONSHIP_TYPES),
        "semantic_sources": sorted(SEMANTIC_SOURCES),
    }


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


@router.post(
    "/tag",
    response_model=RelationshipDTO,
    summary="Tag an article relationship with a semantic type",
    description=(
        "Curation endpoint: creates or updates a REFERS_TO relationship with "
        "semantic metadata. Requires the X-Curation-Key header."
    ),
    tags=["relationships"],
    dependencies=[Depends(require_curation_key)],
)
def tag(
    body: RelationshipTagRequest,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> RelationshipDTO:
    try:
        source_id = resolve_article_id(store, body.source_article)
        target_id = resolve_article_id(store, body.target_article)
        edge = tag_relationship(
            store,
            source_article_id=source_id,
            target_article_id=target_id,
            semantic_type=body.semantic_type,
            explanation=body.explanation,
            semantic_source=body.semantic_source,
            expert_badge=body.expert_badge,
            created_by=body.created_by,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return RelationshipDTO.from_edge(edge)


@router.post(
    "/{edge_id}/vote",
    response_model=RelationshipVoteResponse,
    summary="Vote on a semantic relationship",
    description=(
        "Community endpoint: increments a relationship's upvote or downvote count. "
        "Requires the X-Write-Key header."
    ),
    tags=["relationships"],
    dependencies=[Depends(require_write_key)],
)
def vote(
    edge_id: str,
    body: RelationshipVoteRequest,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> RelationshipVoteResponse:
    try:
        updated = vote_relationship(store, edge_id, body.vote)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if updated is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    return RelationshipVoteResponse(
        edge_id=edge_id,
        community_votes=CommunityVotes(
            upvotes=int(updated.get("community_upvotes") or 0),
            downvotes=int(updated.get("community_downvotes") or 0),
        ),
    )
