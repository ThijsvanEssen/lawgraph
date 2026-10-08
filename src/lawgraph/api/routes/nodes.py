from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import parse_choices
from lawgraph.api.schemas.nodes import (
    DROP_PROPS_KEYS_GRAPH,
    BaseNodeDTO,
    NeighborBucketDTO,
    NeighborDTO,
    NodeGraphResponse,
    NodeNeighborhoodEdge,
    NodeNeighborhoodResponse,
    NodeNeighborsDTO,
    node_type_of,
)
from lawgraph.config.constants import EDGE_STATUS_CANONIEK, EDGE_STATUS_VOORGESTELD
from lawgraph.core.cache import _MISSING, TTLCache
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType
from lawgraph.core.relations import RELATION_NAMES
from lawgraph.db import GraphStore
from lawgraph.db.queries.nodes import (
    DEFAULT_BUCKET_LIMIT,
    NeighborFilter,
    NodeNotFoundError,
    UnsupportedCollectionError,
    get_node_neighborhood,
    get_node_with_neighbors,
)
from lawgraph.db.queries.overlay import (
    HEAT_MAX_LIMIT,
    get_heat_counts,
    get_in_flux_counts,
    stored_heat,
)

router = APIRouter()
logger = get_logger(__name__)

# In-memory TTL cache for the bulk overlay endpoints. Heat/in-flux are
# slow-moving signals (recompute on every page load is wasteful) and the
# AQL pass takes ~400 ms uncached. A 60 s TTL caps the lag at one slow
# request per minute regardless of concurrent viewers. maxsize=128 covers
# all realistic (months, min_count) combinations with a bounded footprint.
_overlay_cache: TTLCache[str, Any] = TTLCache(maxsize=128)


# The two overlays answer raw JSON: validating a map of 40,000 keys through a response
# model took about 200 ms a request. The schema says what the map is.
_COUNT_PER_NODE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Node id (`collection/key`) to count.",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                    "example": {"articles/bwbr0001854_287": 3},
                }
            }
        },
    }
}


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
    responses=_COUNT_PER_NODE,
)
def bulk_in_flux(
    store: Annotated[GraphStore, Depends(get_store)],
) -> JSONResponse:
    """Return all nodes that have at least one VOORGESTELD edge, with counts."""
    cached = _overlay_cache.get("in_flux")
    if cached is _MISSING:
        cached = get_in_flux_counts(store)
        _overlay_cache.set("in_flux", cached)
    return JSONResponse(cached)


# The nodes a request may name, and how many the map of the whole graph keeps.
HEAT_MAX_IDS = 500
HEAT_LIMIT = 10_000


@router.get(
    "/heat",
    summary="Bulk activity score per node (heat layer)",
    description=(
        "A map of node id → activity count over the past N months, where "
        "activity is the number of incoming edges created in that window. "
        "Pass months=3 for a 90-day window. `ids` (comma-separated node ids, at most "
        f"{HEAT_MAX_IDS}) counts those nodes alone, the ones a view draws; without it the "
        "`limit` nodes with the highest counts (the whole graph has 1.85 million), as "
        "`semantic graph-heat` last counted them; 503 until it has."
    ),
    tags=["nodes"],
    response_class=JSONResponse,
    responses=_COUNT_PER_NODE,
)
def bulk_heat(
    store: Annotated[GraphStore, Depends(get_store)],
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
    ids: str | None = Query(
        default=None,
        description=f"Comma-separated node ids to count, at most {HEAT_MAX_IDS}.",
    ),
    limit: int = Query(
        default=HEAT_LIMIT,
        ge=1,
        le=HEAT_MAX_LIMIT,
        description="Without ids: the nodes with the highest counts, this many.",
    ),
) -> JSONResponse:
    """Return activity counts per node for the heat-layer overlay."""
    if ids is not None:
        wanted = sorted({i.strip() for i in ids.split(",") if i.strip()})
        if len(wanted) > HEAT_MAX_IDS:
            raise HTTPException(status_code=422, detail=f"At most {HEAT_MAX_IDS} ids.")
        return JSONResponse(
            get_heat_counts(store, months=months, min_count=min_count, ids=wanted)
        )
    kept = stored_heat(store, months, min_count, limit)
    if kept is None:
        raise HTTPException(
            status_code=503,
            detail="The heat of the whole graph is not counted yet (semantic graph-heat).",
            headers={"Retry-After": "3600"},
        )
    return JSONResponse(kept)


def neighbor_filter(
    relations: Annotated[
        str | None,
        Query(description="Comma-separated relations to keep (`REFERS_TO,PART_OF`)."),
    ] = None,
    node_types: Annotated[
        str | None,
        Query(
            description="Comma-separated node types to keep (`article,judgment`).",
        ),
    ] = None,
    direction: Annotated[
        Literal["outbound", "inbound"] | None,
        Query(description="Keep the edges that leave (`outbound`) or reach the node."),
    ] = None,
    status: Annotated[
        str | None,
        Query(description="Keep the edges of this status (`canoniek`, `voorgesteld`)."),
    ] = None,
) -> NeighborFilter:
    """The edges the caller asks for; 422 for a relation, type or status that does not exist."""
    statuses = (EDGE_STATUS_CANONIEK, EDGE_STATUS_VOORGESTELD)
    if status is not None and status not in statuses:
        raise HTTPException(
            status_code=422,
            detail=f"unknown status: {status}; allowed: {', '.join(statuses)}",
        )
    return NeighborFilter(
        relations=parse_choices(relations, RELATION_NAMES, "relations"),
        node_types=parse_choices(node_types, [t.value for t in NodeType], "node_types"),
        direction=direction,
        status=status,
    )


NeighborFilterParams = Annotated[NeighborFilter, Depends(neighbor_filter)]


@router.get(
    "/{collection}/{key}",
    response_model=NodeGraphResponse,
    summary="Explore a node and its neighbors",
    description=(
        "Fetches a node from the given collection and returns its neighbors from "
        "the unified edge collection in buckets, one per relation, direction and "
        "neighbor collection. Each neighbor carries the edge that leads to it: "
        "`edge_id`, `status`, `confidence` and `meta`. A bucket holds one page "
        "(`limit` neighbors from `offset`, in the same order on every request), "
        "its `total`, and the `next_offset` of the following page (null on the "
        "last). `relations`, `node_types`, `direction` and `status` narrow the "
        "edges; the totals count what remains."
    ),
    tags=["nodes"],
)
def get_node_graph(
    collection: str,
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    filters: NeighborFilterParams,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=200,
            description="Neighbors per bucket, not per response.",
        ),
    ] = DEFAULT_BUCKET_LIMIT,
    offset: Annotated[
        int,
        Query(ge=0, description="Neighbors to skip in every bucket."),
    ] = 0,
) -> NodeGraphResponse:
    """Return a node together with a page of its incoming/outgoing neighbors per bucket."""
    try:
        data = get_node_with_neighbors(
            store, collection, key, filters=filters, limit=limit, offset=offset
        )
    except UnsupportedCollectionError as err:
        logger.debug("Node lookup %s/%s failed: %s", collection, key, err)
        raise HTTPException(status_code=400, detail=str(err)) from err
    except NodeNotFoundError as err:
        logger.debug("Node lookup %s/%s failed: %s", collection, key, err)
        raise HTTPException(status_code=404, detail=str(err)) from err

    buckets = [
        NeighborBucketDTO(
            relation=bucket.facet.relation,
            direction=bucket.facet.direction,
            collection=bucket.facet.collection,
            type=node_type_of(bucket.facet.collection),
            total=bucket.facet.count,
            next_offset=bucket.next_offset,
            items=[
                NeighborDTO.from_entry(
                    doc=entry.doc,
                    edge=entry.edge,
                    direction=entry.direction,
                    confidence=entry.confidence,
                )
                for entry in bucket.entries
            ],
        )
        for bucket in data.buckets
    ]
    return NodeGraphResponse(
        node=BaseNodeDTO.from_document(
            data.node, drop_props_keys=DROP_PROPS_KEYS_GRAPH
        ),
        neighbors=NodeNeighborsDTO(
            total=sum(bucket.total for bucket in buckets), buckets=buckets
        ),
    )


@router.get(
    "/{collection}/{key}/neighborhood",
    response_model=NodeNeighborhoodResponse,
    summary="BFS neighborhood around a node",
    description=(
        "Returns every node and edge within `depth` hops of the focal node in "
        "a single traversal query. `relations` and `status` restrict the edges "
        "the traversal follows, `direction` restricts it to edges leaving "
        "(`outbound`) or reaching (`inbound`) each node on the way, and "
        "`node_types` to paths through nodes of those types (the focal node is "
        "always included)."
    ),
    tags=["nodes"],
)
def get_node_neighborhood_route(
    collection: str,
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    filters: NeighborFilterParams,
    depth: Annotated[int, Query(ge=1, le=4)] = 3,
    cap: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> NodeNeighborhoodResponse:
    try:
        data = get_node_neighborhood(
            store, collection, key, depth=depth, cap=cap, filters=filters
        )
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
