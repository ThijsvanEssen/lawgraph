"""Generic node DTOs: the base node payload, neighbour lists and the node graph views."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.core.models import TYPE_OF_COLLECTION
from lawgraph.core.tk_links import tk_url

# Props a node response leaves out by default: none (the graph views drop the large ones).
_DROP_PROPS_KEYS: tuple[str, ...] = ()


# Props that bloat the wire size of graph-view payloads without serving any
# frontend rendering need. Stripped from focal node + every neighbor on the
# /api/nodes/{coll}/{key} response. The detail endpoints
# (/api/judgments/{ecli}, /api/articles/...) still return them when the
# reader actually needs the body.
DROP_PROPS_KEYS_GRAPH = (
    "text",
    "paragraphs",
    "parties",
    "subjects",
    "judgment_metadata",
    "raw_data",
    "raw",  # documents carry the source TK payload here
    "entries",  # annexes carry their table rows here
)


def node_type_of(collection: str) -> str:
    node_type = TYPE_OF_COLLECTION.get(collection)
    return node_type.value if node_type else ""


def _build_node_payload(
    doc: dict[str, Any], *, drop_props_keys: tuple[str, ...] | None = None
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    raw_props = doc.get("props")
    if isinstance(raw_props, dict):
        props = raw_props
    sanitized = {
        key: value for key, value in props.items() if key not in (drop_props_keys or ())
    }
    link = tk_url(doc.get("type"), props)
    if link:
        sanitized["tk_url"] = link
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "collection": doc["_id"].split("/", 1)[0] if "/" in doc["_id"] else doc["_id"],
        "type": doc.get("type", ""),
        "display_name": props.get("display_name"),
        "labels": list(doc.get("labels") or []),
        "props": sanitized or None,
    }


class BaseNodeDTO(BaseModel):
    """Common node representation used by multiple responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> BaseNodeDTO:
        payload = _build_node_payload(doc, drop_props_keys=drop_props_keys)
        return cls(**payload)


class NeighborDTO(BaseModel):
    """A neighbour with the edge that leads to it, used by the generic node explorer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None
    edge_id: str
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None
    status: str | None
    meta: dict[str, Any] | None

    @classmethod
    def from_entry(
        cls,
        doc: dict[str, Any],
        edge: dict[str, Any],
        direction: Literal["outbound", "inbound"],
        confidence: float | None,
    ) -> NeighborDTO:
        payload = _build_node_payload(doc, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
        meta = edge.get("meta")
        return cls(
            **payload,
            edge_id=edge["_key"],
            relation=edge.get("relation"),
            direction=direction,
            confidence=confidence,
            status=edge.get("status"),
            meta=meta if isinstance(meta, dict) else None,
        )


class NeighborBucketDTO(BaseModel):
    """The neighbours that share a relation, a direction and a collection: one page of them."""

    model_config = ConfigDict(extra="forbid")

    relation: str | None
    direction: Literal["outbound", "inbound"]
    collection: str
    type: str
    total: int
    next_offset: int | None
    items: list[NeighborDTO]


class NodeNeighborsDTO(BaseModel):
    """Neighbors returned by /api/nodes/{collection}/{key}."""

    model_config = ConfigDict(extra="forbid")

    total: int
    buckets: list[NeighborBucketDTO] = Field(default_factory=list)


class NodeFacetDTO(BaseModel):
    """How many edges of a node share a relation, a direction and a neighbour collection."""

    model_config = ConfigDict(extra="forbid")

    relation: str | None
    direction: Literal["outbound", "inbound"]
    collection: str
    type: str
    count: int


class NodeFacetsResponse(BaseModel):
    """Response for GET /api/nodes/{collection}/{key}/facets."""

    model_config = ConfigDict(extra="forbid")

    items: list[NodeFacetDTO]
    total: int


class NodeGraphResponse(BaseModel):
    """Response for GET /api/nodes/{collection}/{key}."""

    model_config = ConfigDict(extra="forbid")

    node: BaseNodeDTO
    neighbors: NodeNeighborsDTO


class NodeNeighborhoodEdge(BaseModel):
    """Edge in a BFS-neighborhood response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    relation: str | None
    confidence: float | None = None
    status: str | None = None


class NodeNeighborhoodResponse(BaseModel):
    """One-shot N-hop neighborhood: focal + reachable nodes + spanning edges."""

    model_config = ConfigDict(extra="forbid")

    focal_id: str
    nodes: list[BaseNodeDTO]
    edges: list[NodeNeighborhoodEdge]
