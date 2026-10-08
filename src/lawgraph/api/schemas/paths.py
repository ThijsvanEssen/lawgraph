"""DTOs of ``GET /api/paths``."""

from __future__ import annotations

from typing import Literal

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
    membership_edge_ids: list[str] = Field(
        default_factory=list,
        description="Of `edge_ids`, those that make a child of a group the path starts or "
        "ends at (`expand=members`).",
    )
    via: dict[str, str] = Field(
        default_factory=dict,
        description="Per end that is a group the path goes through a child of "
        "(`expand=members`): the child (`factions/vvd`: `members/…`).",
    )


class GroupExpandedDTO(BaseModel):
    """How many children of a group a path search started from."""

    model_config = ConfigDict(extra="forbid")

    used: int
    total: int


class PathsResponse(BaseModel):
    """Response for GET /api/paths."""

    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(
        description="The nodes asked for, each once, in their order."
    )
    max_depth: int
    relations: list[str] | None = Field(
        default=None,
        description="The relations the paths keep to, as asked; null for all.",
    )
    through_laws: bool = Field(
        default=False,
        description="Whether a path may pass through a law by its articles (`PART_OF`).",
    )
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
    expand: Literal["none", "members"] = "none"
    expanded: dict[str, GroupExpandedDTO] = Field(
        default_factory=dict,
        description="Per group of `ids` (`expand=members`): how many of its children the "
        "search started from (`used`, at most `expand_cap`) of how many it has (`total`).",
    )
    partial: bool = Field(
        default=False,
        description="The search ran past its time: the paths found by then; another pair "
        "may have one.",
    )
