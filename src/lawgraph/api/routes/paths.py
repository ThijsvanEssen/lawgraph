"""``GET /api/paths``: the shortest paths between chosen nodes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.nodes import (
    DROP_PROPS_KEYS_GRAPH,
    BaseNodeDTO,
    NodeNeighborhoodEdge,
)
from lawgraph.api.schemas.paths import PathDTO, PathsResponse
from lawgraph.db import GraphStore
from lawgraph.db.queries.paths import get_paths
from lawgraph.db.schema import NODE_COLLECTIONS

router = APIRouter()

_MIN_IDS, _MAX_IDS = 2, 5


def _node_ids(value: str) -> list[str]:
    """The ids of *value* (comma-separated), each once; 422 for fewer than two, more than
    five, or one that is no ``collection/key`` of a node collection."""
    ids = list(dict.fromkeys(p.strip() for p in value.split(",") if p.strip()))
    if not _MIN_IDS <= len(ids) <= _MAX_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"ids: {_MIN_IDS} to {_MAX_IDS} node ids, comma-separated",
        )
    wrong = [
        i
        for i in ids
        if "/" not in i
        or not i.split("/", 1)[1]
        or i.split("/")[0] not in NODE_COLLECTIONS
    ]
    if wrong:
        raise HTTPException(
            status_code=422, detail=f"not a node id: {', '.join(wrong)}"
        )
    return ids


@router.get(
    "",
    response_model=PathsResponse,
    summary="The shortest paths between chosen nodes",
    description=(
        "For every pair of `ids` (2 to 5 node ids, `collection/key`, comma-separated), "
        "the shortest path of at most `max_depth` edges between them, following edges in "
        "either direction, with every node and edge on the paths: the nodes between "
        "a member and an article (a document they signed, its dossier, the law it made, "
        "the change). No edge is derived. 404 when one of the nodes is not there."
    ),
    tags=["paths"],
)
def get_paths_route(
    store: Annotated[GraphStore, Depends(get_store)],
    ids: Annotated[
        str, Query(description="Node ids, comma-separated: `members/x,articles/y`")
    ],
    max_depth: Annotated[int, Query(ge=1, le=4)] = 4,
) -> PathsResponse:
    asked = _node_ids(ids)
    missing = [
        i
        for i in asked
        if not store.has_node(*i.split("/", 1))  # type: ignore[arg-type]
    ]
    if missing:
        raise HTTPException(status_code=404, detail=f"not found: {', '.join(missing)}")
    data = get_paths(store, asked, max_depth)
    return PathsResponse(
        ids=asked,
        max_depth=max_depth,
        paths=[
            PathDTO(
                source=p.source,
                target=p.target,
                length=len(p.edges),
                node_ids=list(p.nodes),
                edge_ids=[f"edges/{e}" for e in p.edges],
            )
            for p in data["paths"]
        ],
        nodes=[
            BaseNodeDTO.from_document(n, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
            for n in data["nodes"]
        ],
        edges=[
            NodeNeighborhoodEdge(
                id=e["_id"],
                source=e["_from"],
                target=e["_to"],
                relation=e.get("relation"),
                confidence=(
                    float(e["confidence"])
                    if isinstance(e.get("confidence"), int | float)
                    else None
                ),
                status=e.get("status"),
            )
            for e in data["edges"]
        ],
        capped=data["capped"],
    )
