"""DTOs of ``GET /api/chains``."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.api.schemas.nodes import BaseNodeDTO, NodeNeighborhoodEdge
from lawgraph.db.queries.chains import AROUND_CAP, FRONTIER_CAP, LEVEL_CAP, TOP_STEPS


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
        "each node they share; it names one."
    )
    weight: float = Field(
        description="How strong the step is: over the nodes its sources share the sum of "
        "1 / ln k, k the sources of the node, plus 1 / ln 2 for the edge between them."
    )


class ChainDTO(StrictModel):
    """A row of steps from one node asked for to the other."""

    node_ids: list[str] = Field(
        description="Its sources in order: the two ends and the sources between them."
    )
    steps: list[ChainStepDTO]
    weight: float = Field(description="The `weight` of its weakest step.")


class ChainBlockDTO(StrictModel):
    """The chains of one length."""

    steps: int = Field(description="The steps of each chain of the block.")
    total: int = Field(
        description="Its chains; 0 when none joins the ends. At least that many when "
        "the block is not `complete`."
    )
    chains: list[ChainDTO] = Field(
        description="The first `limit`, the strongest first (the weakest step, then the "
        "steps together, then the ids of their sources), each source between the ends "
        "in one of them only."
    )
    complete: bool = Field(
        description="The search read all this length needs: false when it ran out of "
        "time or left a way out, and then `total` is a lower bound."
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
        description="The search left a way out: more than "
        f"{LEVEL_CAP:,} sources of an end (of an end that is no source more than "
        f"{AROUND_CAP:,} neighbours), more than {FRONTIER_CAP} of a level of a longer "
        f"search, more than {TOP_STEPS} steps of one, or one of two ways to a source: a "
        "chain may have been missed."
    )
    partial: bool = Field(
        description="The search ran past its time: the chains found by then."
    )
