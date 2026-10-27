"""DTOs of ``GET /api/chains``."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.api.schemas.nodes import BaseNodeDTO, NodeNeighborhoodEdge
from lawgraph.db.queries.chains import LEVEL_CAP, PAIR_CAP


class ChainStepDTO(StrictModel):
    """One step of a chain: two sources, joined by an edge or by a node both touch."""

    source: str = Field(description="The id of the source it starts at.")
    target: str = Field(description="The id of the source it ends at.")
    via: str | None = Field(
        description="The node both sources share (a paper that names both); null when "
        "an edge joins them."
    )
    edge_ids: list[str] = Field(
        description="Its edges from `source`: the one to `target`, or the one to `via` "
        "and the one from `via` to `target`."
    )
    ways: int = Field(
        description="The ways this step has: the edge between its sources, if any, and "
        "each node they share; it names the strongest."
    )


class ChainDTO(StrictModel):
    """A row of steps from one node asked for to the other."""

    node_ids: list[str] = Field(
        description="Its sources in order: the two ends and the sources between them."
    )
    steps: list[ChainStepDTO]
    weight: int = Field(
        description="How often the sources between the ends are cited together "
        "(`inbound_citation_count`); 0 for one step."
    )


class ChainBlockDTO(StrictModel):
    """The chains of one length."""

    steps: int = Field(description="The steps of each chain of the block.")
    total: int = Field(description="Its chains; 0 when none joins the ends.")
    chains: list[ChainDTO] = Field(
        description="The first `limit`, the heaviest first, then by the ids of their "
        "sources."
    )
    complete: bool = Field(
        description="The search read all this length needs: false when it ran out of "
        "time or a level reached its cap, and then 0 does not mean none."
    )


class ChainsResponse(StrictModel):
    """Response for GET /api/chains."""

    ids: list[str] = Field(description="The two nodes asked for, in their order.")
    max_steps: int
    limit: int
    blocks: list[ChainBlockDTO] = Field(
        description="One block per length from 1 to `max_steps`, each there when empty."
    )
    nodes: list[BaseNodeDTO] = Field(
        description="Every node on the chains of the blocks, each once."
    )
    edges: list[NodeNeighborhoodEdge] = Field(
        description="Every edge on the chains of the blocks, each once."
    )
    capped: bool = Field(
        description=f"A level of the search reached its cap ({LEVEL_CAP:,} nodes, or the "
        "edges of a hub its share of the level) or the chains of three steps theirs "
        f"({PAIR_CAP:,}): a chain around a hub may have been missed."
    )
    partial: bool = Field(
        description="The search ran past its time: the chains found by then."
    )
