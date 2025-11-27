from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_node_with_neighbors
from lawgraph.api.schemas import (
    BaseNodeDTO,
    NeighborDTO,
    NodeGraphResponse,
    NodeNeighborsDTO,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/{collection}/{key}",
    response_model=NodeGraphResponse,
    summary="Verken een node en zijn strikte/semantische buren",
    description=(
        "Haalt een node uit de opgegeven collectie op en levert zowel de "
        "`edges_strict` als `edges_semantic` buren, inclusief richting en confidence."
    ),
    tags=["nodes"],
)
async def get_node_graph(
    collection: str,
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> NodeGraphResponse:
    """Return a node together with incoming/outgoing strict and semantic neighbors."""
    try:
        data = get_node_with_neighbors(store, collection, key)
    except ValueError as err:
        message = str(err)
        status = 400 if "unsupported" in message else 404
        logger.debug("Node lookup %s/%s failed: %s", collection, key, message)
        raise HTTPException(status_code=status, detail=message) from err

    strict_neighbors = [
        NeighborDTO.from_entry(
            doc=entry.doc,
            relation=entry.relation,
            direction=entry.direction,
            confidence=entry.confidence,
        )
        for entry in data.strict_neighbors
    ]
    semantic_neighbors = [
        NeighborDTO.from_entry(
            doc=entry.doc,
            relation=entry.relation,
            direction=entry.direction,
            confidence=entry.confidence,
        )
        for entry in data.semantic_neighbors
    ]

    neighbors = NodeNeighborsDTO(strict=strict_neighbors, semantic=semantic_neighbors)
    return NodeGraphResponse(
        node=BaseNodeDTO.from_document(data.node),
        neighbors=neighbors,
    )
