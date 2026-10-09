"""Generic node DTOs: the base node payload, neighbour lists and the node graph views."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import WithPath
from lawgraph.core.documents import chamber_of, document_sender, paper_number
from lawgraph.core.models import TYPE_OF_COLLECTION, NodeType
from lawgraph.core.tk_links import tk_url
from lawgraph.db._rows import GRAPH_PROPS_LEFT_OUT

# Props a node response leaves out by default: none (the graph views drop the large ones).
_DROP_PROPS_KEYS: tuple[str, ...] = ()


# Props the graph views leave out of every node, the node itself too (``db/_rows.py``; a
# neighbour leaves out more, in its SQL: ``NEIGHBOUR_PROPS_LEFT_OUT``).
DROP_PROPS_KEYS_GRAPH = GRAPH_PROPS_LEFT_OUT


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
    if doc.get("type") == NodeType.DOCUMENT.value and "number" not in props:
        # A paper's number as its chamber cites it, under the name an EK paper stores it.
        number = paper_number(chamber_of(doc.get("labels")), props)
        if number:
            sanitized["number"] = number
        sender = document_sender(props.get("actors"), props.get("date"))
        if sender:
            sanitized["sender"] = sender
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "collection": doc["_id"].split("/", 1)[0] if "/" in doc["_id"] else doc["_id"],
        "type": doc.get("type", ""),
        "display_name": props.get("display_name"),
        "labels": list(doc.get("labels") or []),
        "props": sanitized or None,
    }


class BaseNodeDTO(WithPath):
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


# The neighbours that carry the short title of their first dossier (``NeighborDTO``).
_NAMED_BY_DOSSIER = ("documents", "activities", "decisions")


class NeighborDTO(WithPath):
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
        names: dict[str, dict[str, Any]] | None = None,
    ) -> NeighborDTO:
        """From the neighbour and its edge; a paper, an activity or a decision has in its
        props ``dossier_short_title``, the name its first dossier goes by (by *names*,
        ``load_dossier_names``; null without one)."""
        payload = _build_node_payload(doc, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
        props = payload.get("props")
        if names is not None and isinstance(props, dict):
            if payload["collection"] in _NAMED_BY_DOSSIER:
                # a copy: the neighbour may be one kept for every request
                props = payload["props"] = dict(props)
                numbers = props.get("dossier_numbers") or [props.get("dossier_number")]
                first = (
                    str(numbers[0] or "")
                    if isinstance(numbers, list) and numbers
                    else ""
                )
                props["dossier_short_title"] = (names.get(first) or {}).get(
                    "short_title"
                )
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
    lid_counts: dict[str, int] | None = Field(
        None,
        description=(
            "Of an article: per lid the edges of the whole bucket cite, how many do "
            '("" for those that cite none; an edge that cites two counts for each); '
            "null when none of them cites a lid."
        ),
    )
    items: list[NeighborDTO]


class NodeNeighborsDTO(BaseModel):
    """Neighbors returned by /api/nodes/{collection}/{key}."""

    model_config = ConfigDict(extra="forbid")

    total: int
    buckets: list[NeighborBucketDTO] = Field(default_factory=list)


class NodeGraphResponse(BaseModel):
    """Response for GET /api/nodes/{collection}/{key}."""

    model_config = ConfigDict(extra="forbid")

    node: BaseNodeDTO
    neighbors: NodeNeighborsDTO
    title: str = Field(
        "",
        description="The title of the node as its page has it (``Artikel 6:162 BW: "
        "onrechtmatige daad``), without the name of the site.",
    )
    description: str = Field("", description="The description of its page.")
    path: str | None = Field(
        None,
        description="Its readable address (``/wetten/BWBR0005289/artikel/6:162``); null "
        "for a node without one.",
    )


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
