"""Node and neighborhood query helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.api.queries._helpers import _ensure_doc, _extract_confidence
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.db import ArangoStore


class NodeNotFoundError(ValueError):
    """Raised when a requested node does not exist in the collection."""


class UnsupportedCollectionError(ValueError):
    """Raised when a collection name is not in the allowed set."""


_ALLOWED_NODE_COLLECTIONS = {
    "instruments",
    "instrument_articles",
    "judgments",
    "procedures",
    "publications",
    "topics",
    "kamerstukdossiers",
    "activiteiten",
    "stemmingen",
    "toezeggingen",
    "commissies",
    "leden",
    "fracties",
}

_DEFAULT_NEIGHBOR_LIMIT = 100
_DEFAULT_PER_RELATION_CAP = 30

# Per-collection per-relation caps for edge sets that grow without bound on a
# single node. Frontends that need more should call collection-specific
# endpoints (e.g. /api/leden/{key}/votes) rather than the generic node graph.
_PER_RELATION_CAPS_BY_COLLECTION: dict[str, dict[str, int]] = {
    "fracties": {"STEMT": 20, "LID_VAN_FRACTIE": 50},
    "leden": {"STEMT": 20, "LID_VAN_FRACTIE": 5},
    "stemmingen": {"STEMT": 50},
}


@dataclass
class NeighborEntry:
    doc: dict[str, Any]
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None


@dataclass
class NodeGraphData:
    node: dict[str, Any]
    neighbors: list[NeighborEntry]


def get_node_with_neighbors(
    store: ArangoStore,
    collection: str,
    key: str,
    *,
    neighbor_limit: int = 100,
) -> NodeGraphData:
    """Retrieve a node together with its unified-edge neighbors."""
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise UnsupportedCollectionError("unsupported collection")
    if not store.db.has_collection(collection):
        raise NodeNotFoundError(f"collection {collection} not found")

    coll = store.db.collection(collection)
    raw_node = coll.get(key)
    if raw_node is None:
        raise NodeNotFoundError("node not found")
    node_doc = _ensure_doc(raw_node)
    if node_doc is None:
        raise NodeNotFoundError("node not found")

    neighbors = _collect_neighbors(
        store, node_doc["_id"], neighbor_limit=neighbor_limit
    )
    return NodeGraphData(node=node_doc, neighbors=neighbors)


def _per_relation_caps(node_id: str) -> dict[str, int]:
    collection = node_id.split("/", 1)[0] if "/" in node_id else ""
    return _PER_RELATION_CAPS_BY_COLLECTION.get(collection, {})


def get_node_neighborhood(
    store: ArangoStore,
    collection: str,
    key: str,
    *,
    depth: int = 3,
    cap: int = 200,
) -> dict[str, Any]:
    """Server-side BFS — returns all nodes + edges within ``depth`` hops.

    Replaces N sequential ``/api/nodes/{coll}/{key}`` round trips. ArangoDB's
    native ANY traversal walks the unified-edge collection in one query;
    ``uniqueVertices: 'global'`` keeps the result deduplicated across
    branches. ``cap`` bounds the discovered vertex count so a hub node
    can't flood the response.

    Edges are taken straight from the traversal — they're already the
    edges that form the BFS spanning tree, but we also surface any other
    edges that connect two vertices in the kept set (filled in by a
    second pass) so the frontend can render the full subgraph.
    """
    if collection not in _ALLOWED_NODE_COLLECTIONS:
        raise UnsupportedCollectionError("unsupported collection")
    if not store.db.has_collection(collection):
        raise NodeNotFoundError(f"collection {collection} not found")

    coll = store.db.collection(collection)
    raw_focal = coll.get(key)
    if raw_focal is None:
        raise NodeNotFoundError("node not found")
    focal_doc = _ensure_doc(raw_focal)
    if focal_doc is None:
        raise NodeNotFoundError("node not found")

    depth = max(1, min(depth, 4))
    cap = max(1, min(cap, 1000))

    # Traverse + dedup vertices in AQL. ``LIMIT cap`` short-circuits when
    # the cap is reached; the focal node is added later so it always lands
    # in the result.
    aql = f"""
    LET focal = DOCUMENT(@focal)
    LET visited = (
        FOR v IN 1..@depth ANY focal {COLLECTION_EDGES}
            OPTIONS {{ uniqueVertices: 'global', bfs: true }}
            LIMIT @cap
            RETURN DISTINCT v
    )
    LET node_ids = APPEND(visited[*]._id, focal._id)
    LET node_id_set = node_ids
    LET edges_between = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from IN node_id_set AND e._to IN node_id_set
            RETURN e
    )
    RETURN {{
        focal: focal,
        nodes: visited,
        edges: edges_between
    }}
    """
    rows = list(
        store.query(
            aql,
            {"focal": focal_doc["_id"], "depth": depth, "cap": cap},
        )
    )
    if not rows:
        return {"focal": focal_doc, "nodes": [], "edges": []}
    return rows[0]


def _collect_neighbors(
    store: ArangoStore,
    node_id: str,
    *,
    neighbor_limit: int = 100,
    per_relation_default: int = 30,
) -> list[NeighborEntry]:
    """Return neighbors with per-relation and overall caps applied in AQL.

    Per-relation caps are picked from a collection-specific table; relations
    without an explicit entry use ``per_relation_default``. Both caps run
    inside ArangoDB so unbounded edge sets (e.g. fracties→stemmingen) never
    materialise on the application side.
    """
    caps = _per_relation_caps(node_id)
    # Bucket by (relation, neighbor_collection) so a single high-fanout
    # relation that fans out to multiple collections (e.g. DEEL_VAN_DOSSIER on
    # a dossier → activiteiten + publications + stemmingen) returns a sample
    # from each, rather than the first N edges in storage order — which would
    # otherwise drop whole collections.
    aql = f"""
    LET buckets = (
        FOR edge IN {COLLECTION_EDGES}
            FILTER edge._from == @node_id OR edge._to == @node_id
            LET neighbor_id = (edge._from == @node_id ? edge._to : edge._from)
            LET direction = (edge._from == @node_id ? 'outbound' : 'inbound')
            LET neighbor_col = SPLIT(neighbor_id, '/')[0]
            COLLECT relation = edge.relation, ncol = neighbor_col INTO group = {{
                edge: edge,
                neighbor_id: neighbor_id,
                direction: direction
            }}
            LET cap = HAS(@caps, relation) ? @caps[relation] : @per_relation_default
            RETURN {{ relation: relation, ncol: ncol, items: SLICE(group, 0, cap) }}
    )
    FOR b IN buckets
        FOR item IN b.items
            LET neighbor = DOCUMENT(item.neighbor_id)
            FILTER neighbor != null
            LIMIT @neighbor_limit
            RETURN {{ edge: item.edge, neighbor: neighbor, direction: item.direction }}
    """
    bind_vars = {
        "node_id": node_id,
        "caps": caps,
        "per_relation_default": per_relation_default,
        "neighbor_limit": neighbor_limit,
    }
    neighbors: list[NeighborEntry] = []
    for row in store.query(aql, bind_vars):
        neighbors.append(
            NeighborEntry(
                doc=row["neighbor"],
                relation=row["edge"].get("relation"),
                direction=row["direction"],
                confidence=_extract_confidence(row["edge"]),
            )
        )
    return neighbors
