"""DTOs of ``GET /api/paths``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.nodes import BaseNodeDTO, NodeNeighborhoodEdge


class PathDTO(BaseModel):
    """The shortest path between two of the nodes asked for."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="The id of the node it starts at.")
    target: str = Field(description="The id of the node it ends at.")
    length: int = Field(description="Its edges, 1 for direct neighbours.")
    node_ids: list[str] = Field(description="Its nodes, from `source` to `target`.")
    edge_ids: list[str] = Field(description="Its edges, in that order.")


class PathsResponse(BaseModel):
    """Response for GET /api/paths."""

    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(
        description="The nodes asked for, each once, in their order."
    )
    max_depth: int
    paths: list[PathDTO] = Field(
        description="For every pair of `ids` that a path of at most `max_depth` edges "
        "joins, the shortest one (of those as short, the one through the lowest ids); a "
        "pair without one has none."
    )
    nodes: list[BaseNodeDTO] = Field(description="Every node on the paths, each once.")
    edges: list[NodeNeighborhoodEdge] = Field(
        description="Every edge on the paths, each once."
    )
    capped: bool = Field(
        description="A level of a search reached its cap (5,000 nodes): a longer way "
        "around a hub may have been missed."
    )
