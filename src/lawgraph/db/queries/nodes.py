"""Node and neighborhood query helpers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.core.models import COLLECTION_OF_TYPE, TYPE_OF_COLLECTION
from lawgraph.db import ArangoStore
from lawgraph.db._rows import edge_doc, node_doc
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

_NODE_COLUMNS = "n.id, n.key, n.type, n.labels, n.props"


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


def _load_node(store: ArangoStore, collection: str, key: str) -> dict[str, Any]:
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise UnsupportedCollectionError("unsupported collection")
    node = store.get_document(collection, key)
    if node is None:
        raise NodeNotFoundError("node not found")
    return node


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
    store: ArangoStore, node_id: str, filters: NeighborFilter
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
    store: ArangoStore,
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
                   e.key AS edge_key, e.from_id, e.to_id, e.doc, {_NODE_COLUMNS}
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
            doc=node_doc(row),
            edge=edge_doc({**row, "key": row["edge_key"]}),
            direction=row["direction"],
        )
        pages.setdefault(
            (row["relation"], row["direction"], row["collection"]), []
        ).append(entry)
    return pages


def _from_their_tables(ids: Iterable[str], columns: str) -> tuple[str, dict[str, Any]]:
    """A read of *columns* (of ``n``) of the nodes *ids* name, each from its own table: the
    ``nodes`` view would look every id up in every table. Empty when no id names a node
    table."""
    tables: dict[str, list[str]] = {}
    for node_id in ids:
        collection = node_id.split("/", 1)[0]
        if collection in _ALLOWED_NODE_COLLECTIONS:
            tables.setdefault(collection, []).append(node_id)
    parts = [
        f"SELECT {columns} FROM {collection} n WHERE n.id = ANY(%(ids_{n})s)"
        for n, collection in enumerate(sorted(tables))
    ]
    params = {f"ids_{n}": tables[c] for n, c in enumerate(sorted(tables))}
    return " UNION ALL ".join(parts), params


# How many neighbours are looked up at a time: a capped walk stops reading them once the
# cap is reached.
_NEIGHBOUR_CHUNK = 500


def _neighbours(
    store: ArangoStore, frontier: list[str], filters: NeighborFilter
) -> Iterator[dict[str, Any]]:
    """``{id, type}`` of every node one edge away from *frontier* along the edges the filters
    let through, each once, by id; a node that is gone is not one."""
    parts = []
    for direction in filters.directions:
        own, other, _ = _EDGE_SIDES[direction]
        parts.append(
            f"SELECT e.{other} AS id FROM edges e"
            f" WHERE e.{own} = ANY(%(frontier)s) {filters.edge_sql('e')}"
        )
    found = list(
        store.query(
            f"SELECT DISTINCT id FROM ({' UNION ALL '.join(parts)}) found ORDER BY id",
            {"frontier": frontier, **filters.edge_params()},
        )
    )
    for start in range(0, len(found), _NEIGHBOUR_CHUNK):
        chunk = found[start : start + _NEIGHBOUR_CHUNK]
        # Each table answers for its own ids from its primary key.
        read, params = _from_their_tables(chunk, "n.id")
        existing = set(store.query(read, params)) if read else set()
        for node_id in chunk:
            if node_id in existing:
                collection = node_id.split("/", 1)[0]
                yield {"id": node_id, "type": TYPE_OF_COLLECTION[collection].value}


def _walk(
    store: ArangoStore, focal_id: str, depth: int, cap: int, filters: NeighborFilter
) -> list[str]:
    """The nodes within *depth* edges of *focal_id*, breadth first, at most *cap* (D9).

    A level is read whole and kept in id order until the cap is reached: what a capped walk
    keeps is a valid prefix of the breadth-first order. A node of a type the filter leaves
    out is seen (it is not reached again) but neither kept nor walked through."""
    seen = {focal_id}
    kept: list[str] = []
    frontier = [focal_id]
    for _ in range(depth):
        level = []
        for node in _neighbours(store, frontier, filters):
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            if (
                filters.node_types is not None
                and node["type"] not in filters.node_types
            ):
                continue
            level.append(node["id"])
            if len(kept) + len(level) == cap:
                return kept + level
        kept += level
        frontier = level
        if not frontier:
            break
    return kept


def get_node_neighborhood(
    store: ArangoStore,
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
    kept = _walk(store, focal["_id"], depth, cap, filters)
    ids = [*kept, focal["_id"]]
    read, params = _from_their_tables(kept, _NODE_COLUMNS)
    nodes = store.query(f"{read} ORDER BY id", params) if read else iter(())
    edges = store.query(
        f"""
        SELECT e.key, e.from_id, e.to_id, e.doc FROM edges e
        WHERE e.from_id = ANY(%(ids)s) AND e.to_id = ANY(%(ids)s) {filters.edge_sql("e")}
        ORDER BY e.key
        """,
        {"ids": ids, **filters.edge_params()},
    )
    return {
        "focal": focal,
        "nodes": [node_doc(row) for row in nodes],
        "edges": [edge_doc(row) for row in edges],
    }
