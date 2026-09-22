"""Node and neighborhood query helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.api.queries._helpers import _ensure_doc, _extract_confidence
from lawgraph.config.constants import COLLECTION_EDGES
from lawgraph.core.models import COLLECTION_OF_TYPE, TYPE_OF_COLLECTION
from lawgraph.db import ArangoStore


class NodeNotFoundError(ValueError):
    """Raised when a requested node does not exist in the collection."""


class UnsupportedCollectionError(ValueError):
    """Raised when a collection name is not in the allowed set."""


Direction = Literal["outbound", "inbound"]
DIRECTIONS: tuple[Direction, ...] = ("outbound", "inbound")

# Every node collection can be explored: one per node type.
_ALLOWED_NODE_COLLECTIONS = frozenset(TYPE_OF_COLLECTION)

DEFAULT_BUCKET_LIMIT = 30

# The edge field that holds the node itself and the one that holds its neighbour, per direction.
_EDGE_SIDES: dict[Direction, tuple[str, str]] = {
    "outbound": ("_from", "_to"),
    "inbound": ("_to", "_from"),
}

# Traversal keyword per direction filter (the node's edges in either direction by default).
_TRAVERSAL_DIRECTION: dict[Direction | None, str] = {
    None: "ANY",
    "outbound": "OUTBOUND",
    "inbound": "INBOUND",
}


@dataclass(frozen=True)
class NeighborFilter:
    """Which edges of a node count: every field left as None lets everything through.

    ``node_types`` restricts the neighbours to these ``NodeType`` values, ``direction`` the
    edges to those that leave (``outbound``) or reach (``inbound``) the node.
    """

    relations: tuple[str, ...] | None = None
    node_types: tuple[str, ...] | None = None
    direction: Direction | None = None
    status: str | None = None

    @property
    def directions(self) -> tuple[Direction, ...]:
        return (self.direction,) if self.direction else DIRECTIONS

    @property
    def collections(self) -> list[str] | None:
        """The collections of ``node_types`` (one collection holds one type)."""
        if self.node_types is None:
            return None
        return [
            collection
            for node_type, collection in COLLECTION_OF_TYPE.items()
            if node_type.value in self.node_types
        ]

    def edge_aql(self, edge: str) -> str:
        """FILTER lines for the relation and status of ``edge``; binds ``relations``, ``status``."""
        lines = []
        if self.relations is not None:
            lines.append(f"FILTER {edge}.relation IN @relations")
        if self.status is not None:
            lines.append(f"FILTER {edge}.status == @status")
        return "\n".join(lines)

    def edge_bind_vars(self) -> dict[str, Any]:
        bind_vars: dict[str, Any] = {}
        if self.relations is not None:
            bind_vars["relations"] = list(self.relations)
        if self.status is not None:
            bind_vars["status"] = self.status
        return bind_vars


NO_FILTER = NeighborFilter()


@dataclass
class NeighborEntry:
    doc: dict[str, Any]
    edge: dict[str, Any]
    direction: Direction

    @property
    def relation(self) -> str | None:
        relation = self.edge.get("relation")
        return relation if isinstance(relation, str) else None

    @property
    def confidence(self) -> float | None:
        return _extract_confidence(self.edge)


@dataclass
class NeighborFacet:
    """The edges of a node that share a relation, a direction and a neighbour collection."""

    relation: str | None
    direction: Direction
    collection: str
    count: int


@dataclass
class NeighborBucket:
    """One facet with the page of its neighbours that was asked for."""

    facet: NeighborFacet
    next_offset: int | None
    entries: list[NeighborEntry]


@dataclass
class NodeGraphData:
    node: dict[str, Any]
    buckets: list[NeighborBucket]


def _load_node(store: ArangoStore, collection: str, key: str) -> dict[str, Any]:
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise UnsupportedCollectionError("unsupported collection")
    if not store.db.has_collection(collection):
        raise NodeNotFoundError(f"collection {collection} not found")
    node_doc = _ensure_doc(store.db.collection(collection).get(key))
    if node_doc is None:
        raise NodeNotFoundError("node not found")
    return node_doc


def get_node_with_neighbors(
    store: ArangoStore,
    collection: str,
    key: str,
    *,
    filters: NeighborFilter = NO_FILTER,
    limit: int = DEFAULT_BUCKET_LIMIT,
    offset: int = 0,
) -> NodeGraphData:
    """A node with its neighbours, in buckets of one relation, direction and collection.

    ``limit`` and ``offset`` page inside every bucket; a bucket says how many edges it has
    and where its next page starts.
    """
    node_doc = _load_node(store, collection, key)
    facets = _count_facets(store, node_doc["_id"], filters)
    pages = _read_pages(store, node_doc["_id"], filters, facets, limit, offset)
    end = offset + limit
    buckets = [
        NeighborBucket(
            facet=facet,
            next_offset=end if end < facet.count else None,
            entries=pages.get((facet.relation, facet.direction, facet.collection), []),
        )
        for facet in facets
    ]
    return NodeGraphData(node=node_doc, buckets=buckets)


def get_node_facets(
    store: ArangoStore,
    collection: str,
    key: str,
    *,
    filters: NeighborFilter = NO_FILTER,
) -> list[NeighborFacet]:
    """How many edges a node has per relation, direction and neighbour collection."""
    node_doc = _load_node(store, collection, key)
    return _count_facets(store, node_doc["_id"], filters)


def _edge_scan_aql(direction: Direction, filters: NeighborFilter) -> str:
    """The edges of ``@node_id`` in one direction that pass ``filters``, as ``e``."""
    own, other = _EDGE_SIDES[direction]
    lines = [f"FOR e IN {COLLECTION_EDGES}", f"FILTER e.{own} == @node_id"]
    if filters.relations is not None or filters.status is not None:
        lines.append(filters.edge_aql("e"))
    if filters.collections is not None:
        lines.append(f"FILTER SPLIT(e.{other}, '/')[0] IN @collections")
    return "\n".join(lines)


def _count_facets(
    store: ArangoStore, node_id: str, filters: NeighborFilter
) -> list[NeighborFacet]:
    """Count the edges of a node per (relation, direction, neighbour collection).

    The edges are grouped and counted inside ArangoDB in one pass over the edges of the
    node, with no document held: a faction has a million ``VOTED`` edges. A collection holds
    one node type, so the neighbours themselves are never read.
    """
    parts = []
    for direction in filters.directions:
        _, other = _EDGE_SIDES[direction]
        parts.append(
            f"""
    LET {direction}_rows = (
        {_edge_scan_aql(direction, filters)}
        COLLECT relation = e.relation, collection = SPLIT(e.{other}, '/')[0]
            WITH COUNT INTO count
        RETURN {{ relation, direction: '{direction}', collection, count }}
    )"""
        )
    names = ", ".join(f"{d}_rows" for d in filters.directions)
    aql = f"""{"".join(parts)}
    FOR facet IN UNION({names}, [])
        SORT facet.relation, facet.direction, facet.collection
        RETURN facet
    """
    bind_vars = {"node_id": node_id, **filters.edge_bind_vars()}
    if filters.collections is not None:
        bind_vars["collections"] = filters.collections
    return [
        NeighborFacet(
            relation=row["relation"],
            direction=row["direction"],
            collection=row["collection"],
            count=row["count"],
        )
        for row in store.query(aql, bind_vars)
    ]


def _read_pages(
    store: ArangoStore,
    node_id: str,
    filters: NeighborFilter,
    facets: Iterable[NeighborFacet],
    limit: int,
    offset: int,
) -> dict[tuple[str | None, str, str], list[NeighborEntry]]:
    """Read ``limit`` neighbours from ``offset`` on in every facet that reaches that far.

    One query per request: each facet reads its own page from the edge index, in ``_key``
    order so that a page is the same on every request. ``limit`` and ``offset`` count edges,
    so an edge whose neighbour is gone leaves its page one short.
    """
    wanted: dict[Direction, list[dict[str, Any]]] = {}
    for facet in facets:
        if facet.count > offset:
            wanted.setdefault(facet.direction, []).append(
                {"relation": facet.relation, "collection": facet.collection}
            )
    if not wanted:
        return {}

    status_aql = "FILTER e.status == @status" if filters.status is not None else ""
    bind_vars: dict[str, Any] = {"node_id": node_id, "offset": offset, "limit": limit}
    if filters.status is not None:
        bind_vars["status"] = filters.status
    parts = []
    for direction, buckets in wanted.items():
        own, other = _EDGE_SIDES[direction]
        bind_vars[f"{direction}_buckets"] = buckets
        parts.append(
            f"""
    LET {direction}_rows = (
        FOR b IN @{direction}_buckets
            LET items = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e.{own} == @node_id AND e.relation == b.relation
                    FILTER SPLIT(e.{other}, '/')[0] == b.collection
                    {status_aql}
                    SORT e._key
                    LIMIT @offset, @limit
                    LET neighbor = DOCUMENT(e.{other})
                    FILTER neighbor != null
                    RETURN {{ edge: e, neighbor: neighbor }}
            )
            RETURN {{
                relation: b.relation,
                direction: '{direction}',
                collection: b.collection,
                items: items
            }}
    )"""
        )
    aql = f"""{"".join(parts)}
    FOR bucket IN UNION({", ".join(f"{d}_rows" for d in wanted)}, [])
        RETURN bucket
    """
    pages: dict[tuple[str | None, str, str], list[NeighborEntry]] = {}
    for row in store.query(aql, bind_vars):
        pages[(row["relation"], row["direction"], row["collection"])] = [
            NeighborEntry(
                doc=item["neighbor"], edge=item["edge"], direction=row["direction"]
            )
            for item in row["items"]
        ]
    return pages


def get_node_neighborhood(
    store: ArangoStore,
    collection: str,
    key: str,
    *,
    depth: int = 3,
    cap: int = 200,
    filters: NeighborFilter = NO_FILTER,
) -> dict[str, Any]:
    """Server-side BFS — returns all nodes + edges within ``depth`` hops.

    ArangoDB's native traversal walks the unified-edge collection in one query;
    ``uniqueVertices: 'global'`` keeps the result deduplicated across branches, and ``cap``
    bounds the discovered vertex count so a hub node cannot flood the response.

    ``filters`` shape the walk itself: a path is followed only along edges of the given
    relations and status, in the given direction, and through nodes of the given types (the
    focal node is always kept). The result also carries every other edge of those relations
    and that status that connects two vertices in the kept set, so the frontend can render
    the full subgraph.
    """
    focal_doc = _load_node(store, collection, key)

    depth = max(1, min(depth, 4))
    cap = max(1, min(cap, 1000))

    # Edge conditions on the whole path (``ALL``) are evaluated by the traversal, which then
    # never leaves along an edge that fails them. Vertices that fail the type condition are
    # emitted once (PRUNE ends the path there) and dropped by the filter behind it.
    walk_filters = []
    if filters.relations is not None:
        walk_filters.append("FILTER p.edges[*].relation ALL IN @relations")
    if filters.status is not None:
        walk_filters.append("FILTER p.edges[*].status ALL == @status")
    prune = ""
    if filters.node_types is not None:
        prune = "PRUNE v._id != @focal AND v.type NOT IN @node_types"
        walk_filters.append("FILTER v.type IN @node_types")
    walk_aql = "\n            ".join(walk_filters)
    direction = _TRAVERSAL_DIRECTION[filters.direction]

    # Traverse + dedup vertices in AQL. ``LIMIT cap`` short-circuits when
    # the cap is reached; the focal node is added later so it always lands
    # in the result.
    aql = f"""
    LET focal = DOCUMENT(@focal)
    LET visited = (
        FOR v, e, p IN 1..@depth {direction} focal {COLLECTION_EDGES}
            {prune}
            OPTIONS {{ uniqueVertices: 'global', bfs: true }}
            {walk_aql}
            LIMIT @cap
            RETURN DISTINCT v
    )
    LET node_ids = APPEND(visited[*]._id, focal._id)
    LET node_id_set = node_ids
    LET edges_between = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from IN node_id_set AND e._to IN node_id_set
            {filters.edge_aql("e")}
            RETURN e
    )
    RETURN {{
        focal: focal,
        nodes: visited,
        edges: edges_between
    }}
    """
    bind_vars: dict[str, Any] = {
        "focal": focal_doc["_id"],
        "depth": depth,
        "cap": cap,
        **filters.edge_bind_vars(),
    }
    if filters.node_types is not None:
        bind_vars["node_types"] = list(filters.node_types)
    rows = list(store.query(aql, bind_vars))
    if not rows:
        return {"focal": focal_doc, "nodes": [], "edges": []}
    return rows[0]
