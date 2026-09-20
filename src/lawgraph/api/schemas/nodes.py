"""Generic node DTOs: the base node payload, neighbour lists and the node graph views."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    "subjects",
    "judgment_metadata",
    "raw_data",
    "raw",  # documents carry the source TK payload here
)


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
    """Neighbor view used by the generic node explorer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None

    @classmethod
    def from_entry(
        cls,
        doc: dict[str, Any],
        relation: str | None,
        direction: Literal["outbound", "inbound"],
        confidence: float | None,
    ) -> NeighborDTO:
        payload = _build_node_payload(doc, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
        return cls(
            **payload, relation=relation, direction=direction, confidence=confidence
        )


class NodeNeighborsDTO(BaseModel):
    """Neighbors returned by /api/nodes/{collection}/{key}."""

    model_config = ConfigDict(extra="forbid")

    all: list[NeighborDTO] = Field(default_factory=list)


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
