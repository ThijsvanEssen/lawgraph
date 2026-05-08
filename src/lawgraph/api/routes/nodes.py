from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_heat_counts,
    get_in_flux_counts,
    get_node_with_neighbors,
)
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
    "/in-flux",
    response_model=dict[str, int],
    summary="Bulk in-flux teller per node",
    description=(
        "Geeft een map van node-ID → aantal open voorgestelde mutaties. "
        "Alleen nodes met ≥1 open mutatie zijn opgenomen. "
        "Gebruik dit om de in-flux ring op graafnodes te renderen."
    ),
    tags=["nodes"],
)
async def bulk_in_flux(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> dict[str, int]:
    """Return all nodes that have at least one VOORGESTELD edge, with counts."""
    return get_in_flux_counts(store)


@router.get(
    "/heat",
    response_model=dict[str, int],
    summary="Bulk activiteitsscore per node (heat layer)",
    description=(
        "Geeft een map van node-ID → activiteitscount over de afgelopen N maanden. "
        "Activiteit = aantal inkomende edges aangemaakt in de periode. "
        "Gebruik months=3 voor een 90-dagenvenster."
    ),
    tags=["nodes"],
)
async def bulk_heat(
    store: Annotated[ArangoStore, Depends(get_store)],
    months: int = Query(
        default=6, ge=1, le=24, description="Terugkijkvenster in maanden"
    ),
) -> dict[str, int]:
    """Return activity counts per node for the heat-layer overlay."""
    return get_heat_counts(store, months=months)


@router.get(
    "/{collection}/{key}",
    response_model=NodeGraphResponse,
    summary="Verken een node en zijn buren",
    description=(
        "Haalt een node uit de opgegeven collectie op en levert alle buren "
        "via de gecombineerde edges-collectie, inclusief richting en confidence."
    ),
    tags=["nodes"],
)
async def get_node_graph(
    collection: str,
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> NodeGraphResponse:
    """Return a node together with all incoming/outgoing neighbors."""
    try:
        data = get_node_with_neighbors(store, collection, key)
    except ValueError as err:
        message = str(err)
        status = 400 if "unsupported" in message else 404
        logger.debug("Node lookup %s/%s failed: %s", collection, key, message)
        raise HTTPException(status_code=status, detail=message) from err

    all_neighbors = [
        NeighborDTO.from_entry(
            doc=entry.doc,
            relation=entry.relation,
            direction=entry.direction,
            confidence=entry.confidence,
        )
        for entry in data.neighbors
    ]

    # strict and semantic are kept as backwards-compat aliases pointing to all neighbors.
    neighbors = NodeNeighborsDTO(
        all=all_neighbors, strict=all_neighbors, semantic=all_neighbors
    )
    return NodeGraphResponse(
        node=BaseNodeDTO.from_document(data.node),
        neighbors=neighbors,
    )
