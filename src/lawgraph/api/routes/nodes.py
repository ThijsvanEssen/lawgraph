from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from lawgraph.api.cache import TTLCache
from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_heat_counts,
    get_in_flux_counts,
    get_node_neighborhood,
    get_node_with_neighbors,
)
from lawgraph.api.schemas import (
    _DROP_PROPS_KEYS_GRAPH,
    BaseNodeDTO,
    NeighborDTO,
    NodeGraphResponse,
    NodeNeighborhoodEdge,
    NodeNeighborhoodResponse,
    NodeNeighborsDTO,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

# In-memory TTL cache for the bulk overlay endpoints. Heat/in-flux are
# slow-moving signals (recompute on every page load is wasteful) and the
# AQL pass takes ~400 ms uncached. A 60 s TTL caps the lag at one slow
# request per minute regardless of concurrent viewers. maxsize=128 covers
# all realistic (months, min_count) combinations with a bounded footprint.
_overlay_cache: TTLCache[str, Any] = TTLCache(maxsize=128)


@router.get(
    "/in-flux",
    summary="Bulk in-flux teller per node",
    description=(
        "Geeft een map van node-ID → aantal open voorgestelde mutaties. "
        "Alleen nodes met ≥1 open mutatie zijn opgenomen. "
        "Gebruik dit om de in-flux ring op graafnodes te renderen."
    ),
    tags=["nodes"],
    response_class=JSONResponse,
)
async def bulk_in_flux(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> JSONResponse:
    """Return all nodes that have at least one VOORGESTELD edge, with counts."""
    cached = _overlay_cache.get("in_flux")
    if cached is None:
        cached = get_in_flux_counts(store)
        _overlay_cache.set("in_flux", cached)
    return JSONResponse(cached)


@router.get(
    "/heat",
    summary="Bulk activiteitsscore per node (heat layer)",
    description=(
        "Geeft een map van node-ID → activiteitscount over de afgelopen N maanden. "
        "Activiteit = aantal inkomende edges aangemaakt in de periode. "
        "Gebruik months=3 voor een 90-dagenvenster."
    ),
    tags=["nodes"],
    # No response_model — Pydantic validation of a 40K-key dict adds
    # ~200 ms per request for zero correctness benefit. Return raw JSON.
    response_class=JSONResponse,
)
async def bulk_heat(
    store: Annotated[ArangoStore, Depends(get_store)],
    months: int = Query(
        default=6, ge=1, le=24, description="Terugkijkvenster in maanden"
    ),
    min_count: int = Query(
        default=1,
        ge=1,
        le=1000,
        description=(
            "Drop nodes with fewer than this many activity hits. Default 1 "
            "returns everything; bump to 2-5 for a much smaller payload "
            "without losing visible heat halos."
        ),
    ),
) -> JSONResponse:
    """Return activity counts per node for the heat-layer overlay."""
    cache_key = f"heat:m={months}:mc={min_count}"
    cached = _overlay_cache.get(cache_key)
    if cached is None:
        cached = get_heat_counts(store, months=months, min_count=min_count)
        _overlay_cache.set(cache_key, cached)
    return JSONResponse(cached)


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
    neighbor_limit: Annotated[
        int,
        Query(
            ge=1,
            le=5000,
            description=(
                "Overall cap on neighbors returned. Per-(relation, neighbor "
                "collection) caps are applied first (e.g. fracties cap STEMT "
                "at 20 per destination collection); the result is then capped "
                "to this overall limit."
            ),
        ),
    ] = 100,
) -> NodeGraphResponse:
    """Return a node together with all incoming/outgoing neighbors."""
    try:
        data = get_node_with_neighbors(
            store, collection, key, neighbor_limit=neighbor_limit
        )
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
        node=BaseNodeDTO.from_document(
            data.node, drop_props_keys=_DROP_PROPS_KEYS_GRAPH
        ),
        neighbors=neighbors,
    )


@router.get(
    "/{collection}/{key}/neighborhood",
    response_model=NodeNeighborhoodResponse,
    summary="BFS-buurt rond een node",
    description=(
        "Levert in één query alle nodes en edges binnen `depth` hops rondom "
        "de focal node. Vervangt N sequentiële `/api/nodes/{coll}/{key}` "
        "calls met één traversal-query."
    ),
    tags=["nodes"],
)
async def get_node_neighborhood_route(
    collection: str,
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    depth: Annotated[int, Query(ge=1, le=4)] = 3,
    cap: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> NodeNeighborhoodResponse:
    try:
        data = get_node_neighborhood(store, collection, key, depth=depth, cap=cap)
    except ValueError as err:
        message = str(err)
        status = 400 if "unsupported" in message else 404
        raise HTTPException(status_code=status, detail=message) from err

    focal = data["focal"]
    nodes = [
        BaseNodeDTO.from_document(n, drop_props_keys=_DROP_PROPS_KEYS_GRAPH)
        for n in data["nodes"]
    ]
    # Focal first so the client can pin layout to it without searching.
    nodes.insert(
        0, BaseNodeDTO.from_document(focal, drop_props_keys=_DROP_PROPS_KEYS_GRAPH)
    )
    edges = [
        NodeNeighborhoodEdge(
            id=e["_id"],
            source=e["_from"],
            target=e["_to"],
            relation=e.get("relation"),
            confidence=(
                float(e.get("confidence"))
                if isinstance(e.get("confidence"), (int, float))
                else None
            ),
            status=e.get("status"),
        )
        for e in data["edges"]
    ]
    return NodeNeighborhoodResponse(focal_id=focal["_id"], nodes=nodes, edges=edges)
