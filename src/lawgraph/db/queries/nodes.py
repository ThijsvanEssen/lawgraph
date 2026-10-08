"""Node and neighborhood query helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.core.models import COLLECTION_OF_TYPE, TYPE_OF_COLLECTION
from lawgraph.db import GraphStore
from lawgraph.db._rows import light_edge_doc, light_node_doc, light_props
from lawgraph.db.queries._helpers import _extract_confidence


class NodeNotFoundError(ValueError):
    """Raised when a requested node does not exist in the collection."""


class UnsupportedCollectionError(ValueError):
    """Raised when a collection name is not in the allowed set."""


Direction = Literal["outbound", "inbound"]
DIRECTIONS: tuple[Direction, ...] = ("outbound", "inbound")

# Every node collection can be explored: one per node type.
_ALLOWED_NODE_COLLECTIONS = frozenset(TYPE_OF_COLLECTION)

DEFAULT_BUCKET_LIMIT = 30

# The columns of an edge that hold the node itself and its neighbour, and the neighbour's
# collection, per direction.
_EDGE_SIDES: dict[Direction, tuple[str, str, str]] = {
    "outbound": ("from_id", "to_id", "to_collection"),
    "inbound": ("to_id", "from_id", "from_collection"),
}

# The columns of a node and an edge as the neighbourhood statement gives them, in order.
_NODE_FIELDS = ("id", "key", "type", "labels", "props")
_EDGE_FIELDS = ("key", "from_id", "to_id", "doc")


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

    def edge_sql(self, edge: str) -> str:
        """Conditions on the relation and status of ``edge``; binds ``relations``,
        ``status``."""
        conditions = []
        if self.relations is not None:
            conditions.append(f"AND {edge}.relation = ANY(%(relations)s)")
        if self.status is not None:
            conditions.append(f"AND {edge}.status = %(status)s")
        return " ".join(conditions)

    def edge_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if self.relations is not None:
            params["relations"] = list(self.relations)
        if self.status is not None:
            params["status"] = self.status
        return params


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


def _load_node(store: GraphStore, collection: str, key: str) -> dict[str, Any]:
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise UnsupportedCollectionError("unsupported collection")
    node = store.get_document(collection, key)
    if node is None:
        raise NodeNotFoundError("node not found")
    return node


def get_node_with_neighbors(
    store: GraphStore,
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
    node = _load_node(store, collection, key)
    facets = _count_facets(store, node["_id"], filters)
    pages = _read_pages(store, node["_id"], filters, facets, limit, offset)
    end = offset + limit
    buckets = [
        NeighborBucket(
            facet=facet,
            next_offset=end if end < facet.count else None,
            entries=pages.get((facet.relation, facet.direction, facet.collection), []),
        )
        for facet in facets
    ]
    return NodeGraphData(node=node, buckets=buckets)


def _count_facets(
    store: GraphStore, node_id: str, filters: NeighborFilter
) -> list[NeighborFacet]:
    """Count the edges of a node per (relation, direction, neighbour collection).

    One pass over the edges of the node, with no document read: a faction has a million
    ``VOTED`` edges. A collection holds one node type, so the neighbours are never read.
    """
    parts = []
    for direction in filters.directions:
        own, _, other_collection = _EDGE_SIDES[direction]
        collections = (
            f"AND e.{other_collection} = ANY(%(collections)s)"
            if filters.collections is not None
            else ""
        )
        parts.append(
            f"""
            SELECT e.relation, '{direction}' AS direction, e.{other_collection} AS collection,
                   count(*)::int AS count
            FROM edges e
            WHERE e.{own} = %(node_id)s {filters.edge_sql("e")} {collections}
            GROUP BY e.relation, e.{other_collection}
            """
        )
    statement = (
        " UNION ALL ".join(parts)
        + " ORDER BY relation NULLS FIRST, direction, collection NULLS FIRST"
    )
    params = {
        "node_id": node_id,
        "collections": filters.collections,
        **filters.edge_params(),
    }
    return [
        NeighborFacet(
            relation=row["relation"],
            direction=row["direction"],
            collection=row["collection"],
            count=row["count"],
        )
        for row in store.query(statement, params)
    ]


def _read_pages(
    store: GraphStore,
    node_id: str,
    filters: NeighborFilter,
    facets: Iterable[NeighborFacet],
    limit: int,
    offset: int,
) -> dict[tuple[str | None, str, str], list[NeighborEntry]]:
    """Read ``limit`` neighbours from ``offset`` on in every facet that reaches that far.

    One query per request: each facet reads its own page of edges in key order, so that a
    page is the same on every request. ``limit`` and ``offset`` count edges, so an edge
    whose neighbour is gone leaves its page one short.
    """
    wanted: dict[Direction, list[NeighborFacet]] = {}
    for facet in facets:
        if facet.count > offset:
            wanted.setdefault(facet.direction, []).append(facet)
    if not wanted:
        return {}
    status = "AND e.status = %(status)s" if filters.status is not None else ""
    params: dict[str, Any] = {
        "node_id": node_id,
        "offset": offset,
        "limit": limit,
        **filters.edge_params(),
    }
    parts = []
    for direction, buckets in wanted.items():
        own, other, other_collection = _EDGE_SIDES[direction]
        params[f"{direction}_relations"] = [b.relation for b in buckets]
        params[f"{direction}_collections"] = [b.collection for b in buckets]
        parts.append(
            f"""
            SELECT b.relation, '{direction}' AS direction, b.collection, b.ord,
                   e.key AS edge_key, e.from_id, e.to_id, e.doc,
                   n.id, n.key, n.type, n.labels, {light_props("n")} AS props
            FROM unnest(%({direction}_relations)s::text[], %({direction}_collections)s::text[])
                WITH ORDINALITY AS b(relation, collection, ord)
            CROSS JOIN LATERAL (
                SELECT * FROM edges e
                WHERE e.{own} = %(node_id)s
                  AND e.relation IS NOT DISTINCT FROM b.relation
                  AND e.{other_collection} = b.collection {status}
                ORDER BY e.key
                LIMIT %(limit)s OFFSET %(offset)s
            ) e
            JOIN nodes n ON n.id = e.{other}
            """
        )
    statement = " UNION ALL ".join(parts) + " ORDER BY direction, ord, edge_key"
    pages: dict[tuple[str | None, str, str], list[NeighborEntry]] = {}
    for row in store.query(statement, params):
        entry = NeighborEntry(
            doc=light_node_doc(row),
            edge=light_edge_doc({**row, "key": row["edge_key"]}),
            direction=row["direction"],
        )
        pages.setdefault(
            (row["relation"], row["direction"], row["collection"]), []
        ).append(entry)
    return pages


# How many neighbours ``lg_walk`` looks up at a time: a capped walk stops looking them up
# once the cap is reached.
_NEIGHBOUR_CHUNK = 500


def _walk_params(
    focal_id: str, depth: int, cap: int, filters: NeighborFilter
) -> dict[str, Any]:
    """The arguments of ``lg_walk`` (``db/schema.py``) for a walk from *focal_id*."""
    return {
        "focal": focal_id,
        "depth": depth,
        "cap": cap,
        "relations": list(filters.relations) if filters.relations is not None else None,
        "status": filters.status,
        "outbound": "outbound" in filters.directions,
        "inbound": "inbound" in filters.directions,
        "collections": filters.collections,
        "tables": sorted(_ALLOWED_NODE_COLLECTIONS),
        "chunk": _NEIGHBOUR_CHUNK,
        **filters.edge_params(),
    }


def get_node_neighborhood(
    store: GraphStore,
    collection: str,
    key: str,
    *,
    depth: int = 3,
    cap: int = 200,
    filters: NeighborFilter = NO_FILTER,
) -> dict[str, Any]:
    """Every node and edge within ``depth`` hops of a node, breadth first.

    ``cap`` bounds the number of nodes so a hub cannot flood the response. ``filters``
    shape the walk itself: it follows only edges of the given relations and status, in the
    given direction, and goes through nodes of the given types (the focal node is always
    kept). The result also carries every other edge of those relations and that status
    between two of the nodes kept, so the frontend can render the full subgraph.
    """
    focal = _load_node(store, collection, key)
    depth = max(1, min(depth, 4))
    cap = max(1, min(cap, 1000))
    # One statement: the walk in the database (breadth first, D9: a level is kept in id
    # order until the cap; a node of a type the filter leaves out is seen but neither kept
    # nor walked through), the nodes it kept, and the edges between them and the focal
    # node.
    found = next(
        store.query(
            f"""
            WITH walked AS (
                SELECT lg_walk(%(focal)s, %(depth)s, %(cap)s, %(relations)s, %(status)s,
                               %(outbound)s, %(inbound)s, %(collections)s, %(tables)s,
                               %(chunk)s) AS ids
            )
            SELECT
                (SELECT coalesce(json_agg(json_build_array(
                     n.id, n.key, n.type, n.labels, {light_props("n")}) ORDER BY n.id), '[]')
                 FROM walked w, nodes n
                 WHERE n.id = ANY(w.ids)
                   -- only the tables of the collections walked to are asked
                   AND n.collection = ANY(ARRAY(
                       SELECT DISTINCT split_part(x, '/', 1) FROM unnest(w.ids) x))
                ) AS nodes,
                (SELECT coalesce(json_agg(json_build_array(
                     e.key, e.from_id, e.to_id, e.doc) ORDER BY e.key), '[]')
                 FROM walked w, edges e
                 WHERE e.from_id = ANY(w.ids || %(focal)s::text)
                   AND e.to_id = ANY(w.ids || %(focal)s::text) {filters.edge_sql("e")})
                    AS edges
            FROM walked
            """,
            _walk_params(focal["_id"], depth, cap, filters),
        )
    )
    nodes = [dict(zip(_NODE_FIELDS, row, strict=True)) for row in found["nodes"]]
    edges = [dict(zip(_EDGE_FIELDS, row, strict=True)) for row in found["edges"]]
    return {
        "focal": focal,
        "nodes": [light_node_doc(row) for row in nodes],
        "edges": [light_edge_doc(row) for row in edges],
    }
