"""``GET /api/chains``: the chains of steps between two chosen nodes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import Invalid
from lawgraph.api.params import is_node_id
from lawgraph.api.schemas.chains import (
    ChainBlockDTO,
    ChainDTO,
    ChainsResponse,
    ChainStepDTO,
)
from lawgraph.api.schemas.nodes import BaseNodeDTO, NodeNeighborhoodEdge
from lawgraph.core.models import parse_node_id
from lawgraph.core.relations import without_unknown_relations
from lawgraph.db import GraphStore
from lawgraph.db.queries import seo as seo_queries
from lawgraph.db.queries.chains import (
    CHAINS_BUDGET,
    LEVEL_CAP,
    MAX_STEPS,
    Block,
    get_chains,
)
from lawgraph.db.queries.not_found import NotFound

router = APIRouter()


def _ends(value: str) -> tuple[str, str]:
    """The two ids of *value* (comma-separated); 422 for any other number, or one that is
    no ``collection/key`` of a node collection."""
    ids = list(dict.fromkeys(p.strip() for p in value.split(",") if p.strip()))
    if len(ids) != 2:
        raise Invalid("ids", "two different node ids, comma-separated.")
    wrong = [i for i in ids if not is_node_id(i)]
    if wrong:
        raise Invalid("ids", f"not a node id: {', '.join(wrong)}.")
    return ids[0], ids[1]


@router.get(
    "",
    response_model=ChainsResponse,
    summary="The chains of steps between two chosen nodes",
    description=(
        "The chains of 1 to `max_steps` steps from one node of `ids` (two node ids, "
        "`collection/key`, comma-separated) to the other. A step joins two sources: by an "
        "edge between them (`via` null: one refers to the other), or by a node with an "
        "edge to both (`via`: what they share, as `/api/nodes/shared` finds it: a paper "
        "that names both, a judgment that cites both). The sources between the ends are "
        "laws and articles (`instruments`, `articles`); what two sources share can be any "
        "node; each node is once in a chain. So two steps are an end, what it shares with "
        "a law, that law, what the law shares with the other end, the other end. One "
        "block per length (1, 2, 3), each there when empty: its `total` and its first "
        "`limit` chains, the heaviest first (the `inbound_citation_count` of the sources "
        "between the ends together), then by their ids. A chain is one row of sources: "
        "its steps name their strongest way (the edge, else the shared node cited most, "
        "then the lowest id) and count their `ways`. The shortest chains first: a source "
        "the ends share or a shorter chain passes starts no longer chain. A chain does not "
        "pass through a law by its articles (the `PART_OF` of an article and its law "
        "counts only where the law is an end), as on `/api/paths`. No edge is derived. "
        f"The search reads levels of at most {LEVEL_CAP:,} nodes (`capped`) for at most "
        f"{CHAINS_BUDGET:.0f} s "
        "(`partial`); a block is `complete` when neither touched it. 404 when a node is "
        "not there."
    ),
    tags=["chains"],
)
def get_chains_route(
    store: Annotated[GraphStore, Depends(get_store)],
    ids: Annotated[
        str,
        Query(
            description="Two node ids, comma-separated: `instruments/x,instruments/y`"
        ),
    ],
    max_steps: Annotated[
        int, Query(ge=1, le=MAX_STEPS, description="The longest chain, in steps.")
    ] = 2,
    limit: Annotated[
        int, Query(ge=1, le=50, description="The chains of a block, at most.")
    ] = 12,
) -> ChainsResponse:
    ends = _ends(ids)
    missing = [i for i in ends if not store.has_node(*parse_node_id(i))]
    if missing:
        raise NotFound("Nodes", ", ".join(missing))
    data = get_chains(store, ends, max_steps, limit)
    # the notes of the publications among them, whose titles their titles read
    notes = seo_queries.notes_of(store, data.nodes)
    return ChainsResponse(
        ids=list(ends),
        max_steps=max_steps,
        limit=limit,
        blocks=[_block(block) for block in data.blocks],
        nodes=[
            BaseNodeDTO.from_document(n, graph=True, note=notes.get(n["id"]))
            for n in data.nodes
        ],
        edges=[
            NodeNeighborhoodEdge.from_doc(e)
            for e in without_unknown_relations(data.edges, lambda e: e.get("relation"))
        ],
        capped=data.capped,
        partial=data.partial,
    )


def _block(block: Block) -> ChainBlockDTO:
    return ChainBlockDTO(
        steps=block.steps,
        total=block.total,
        complete=block.complete,
        chains=[
            ChainDTO(
                node_ids=list(chain.sources),
                weight=chain.weight,
                steps=[
                    ChainStepDTO(
                        source=step.source,
                        target=step.target,
                        via=step.via,
                        edge_ids=[f"edges/{e}" for e in step.edges],
                        ways=step.ways,
                    )
                    for step in chain.steps
                ],
            )
            for chain in block.chains
        ],
    )
