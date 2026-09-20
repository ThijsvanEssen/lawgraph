from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from lawgraph.api.cache import _MISSING, TTLCache
from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.nodes import (
    NodeNotFoundError,
    UnsupportedCollectionError,
    get_node_neighborhood,
    get_node_with_neighbors,
)
from lawgraph.api.queries.overlay import get_heat_counts, get_in_flux_counts
from lawgraph.api.schemas.nodes import (
    DROP_PROPS_KEYS_GRAPH,
    BaseNodeDTO,
    NeighborDTO,
    NodeGraphResponse,
    NodeNeighborhoodEdge,
    NodeNeighborhoodResponse,
    NodeNeighborsDTO,
)
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

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
    summary="Bulk in-flux count per node",
    description=(
        "A map of node id → number of open proposed changes. Only nodes with "
        "at least one open change are included. Use it to render the in-flux "
        "ring on graph nodes."
    ),
    tags=["nodes"],
    response_class=JSONResponse,
)
def bulk_in_flux(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> JSONResponse:
    """Return all nodes that have at least one VOORGESTELD edge, with counts."""
    cached = _overlay_cache.get("in_flux")
    if cached is _MISSING:
        cached = get_in_flux_counts(store)
        _overlay_cache.set("in_flux", cached)
    return JSONResponse(cached)


@router.get(
    "/heat",
    summary="Bulk activity score per node (heat layer)",
    description=(
        "A map of node id → activity count over the past N months, where "
        "activity is the number of incoming edges created in that window. "
        "Pass months=3 for a 90-day window."
    ),
    tags=["nodes"],
    # No response_model — Pydantic validation of a 40K-key dict adds
    # ~200 ms per request for zero correctness benefit. Return raw JSON.
    response_class=JSONResponse,
)
def bulk_heat(
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
    if cached is _MISSING:
        cached = get_heat_counts(store, months=months, min_count=min_count)
        _overlay_cache.set(cache_key, cached)
    return JSONResponse(cached)


@router.get(
    "/{collection}/{key}",
    response_model=NodeGraphResponse,
    summary="Explore a node and its neighbors",
    description=(
        "Fetches a node from the given collection and returns all its "
        "neighbors from the unified edge collection, with direction and "
        "confidence."
    ),
    tags=["nodes"],
)
def get_node_graph(
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
                "collection) caps are applied first (e.g. factions cap VOTED "
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
    except UnsupportedCollectionError as err:
        logger.debug("Node lookup %s/%s failed: %s", collection, key, err)
        raise HTTPException(status_code=400, detail=str(err)) from err
    except NodeNotFoundError as err:
        logger.debug("Node lookup %s/%s failed: %s", collection, key, err)
        raise HTTPException(status_code=404, detail=str(err)) from err

    all_neighbors = [
        NeighborDTO.from_entry(
            doc=entry.doc,
            relation=entry.relation,
            direction=entry.direction,
            confidence=entry.confidence,
        )
        for entry in data.neighbors
    ]

    neighbors = NodeNeighborsDTO(all=all_neighbors)
    return NodeGraphResponse(
        node=BaseNodeDTO.from_document(
            data.node, drop_props_keys=DROP_PROPS_KEYS_GRAPH
        ),
        neighbors=neighbors,
    )


@router.get(
    "/{collection}/{key}/neighborhood",
    response_model=NodeNeighborhoodResponse,
    summary="BFS neighborhood around a node",
    description=(
        "Returns every node and edge within `depth` hops of the focal node in "
        "a single traversal query."
    ),
    tags=["nodes"],
)
def get_node_neighborhood_route(
    collection: str,
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    depth: Annotated[int, Query(ge=1, le=4)] = 3,
    cap: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> NodeNeighborhoodResponse:
    try:
        data = get_node_neighborhood(store, collection, key, depth=depth, cap=cap)
    except UnsupportedCollectionError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except NodeNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err

    focal = data["focal"]
    nodes = [
        BaseNodeDTO.from_document(n, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
        for n in data["nodes"]
    ]
    # Focal first so the client can pin layout to it without searching.
    nodes.insert(
        0, BaseNodeDTO.from_document(focal, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
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
