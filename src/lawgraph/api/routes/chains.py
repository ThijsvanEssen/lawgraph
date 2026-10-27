"""``GET /api/chains``: the chains of steps between two chosen nodes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

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
from lawgraph.core.logging import get_logger
from lawgraph.core.models import parse_node_id
from lawgraph.core.relations import without_unknown_relations
from lawgraph.db import GraphStore
from lawgraph.db.queries import seo as seo_queries
from lawgraph.db.queries.chains import (
    CHAINS_BUDGET,
    EXACT_STEPS,
    FRONTIER_CAP,
    LEVEL_CAP,
    MAX_STEPS,
    TOP_STEPS,
    Block,
    get_chains,
)
from lawgraph.db.queries.not_found import NotFound
from lawgraph.db.queries.source_steps import THROUGH_CAP, steps_built

logger = get_logger(__name__)
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
        "`collection/key`, comma-separated) to the other. A step joins two sources (laws "
        "and articles, `instruments`, `articles`): by an edge between them (`via` null: "
        "one refers to the other), or by a node with an edge to both and to at most "
        f"{THROUGH_CAP} sources (`via`: what they share, as `/api/nodes/shared` finds it: "
        "a paper that names both, a judgment that cites both). An end may be any node. "
        "So two steps are an end, what it shares with a law, that law, what the law "
        "shares with the other end, the other end. Each node is once in a chain. A step's "
        "`weight` is the sum over the nodes its sources share of 1 / ln k, k the sources "
        "of the node, plus 1 / ln 2 for an edge between them; a chain is as strong as its "
        "weakest step (`weight`). One block per length (1 to `max_steps`), each there when "
        "empty: its `total` and its first `limit` chains, the strongest first (the weakest "
        "step, then the steps together, then the ids), each source between the ends in one "
        "of them only. Each step names its way (the edge, else the node they share with the "
        "fewest sources, then the lowest id) and counts its `ways`. The shortest chains "
        "first: a source the ends share or a shorter chain passes starts no longer chain. "
        "A chain does not pass through a law by its articles (the `PART_OF` of an article "
        "and its law counts only where the law is an end). No edge is derived. Up to "
        f"{EXACT_STEPS} steps every chain is counted (of at most {LEVEL_CAP:,} sources of "
        f"an end); longer chains are searched best first, {FRONTIER_CAP} sources a level "
        f"with their {TOP_STEPS} strongest steps each, and their `total` is then at least "
        f"that many. A search that left a way out is `capped`, one past {CHAINS_BUDGET:.0f} "
        "s `partial`; a block is `complete` when neither touched it. Searched on the steps "
        "`semantic graph-steps` builds: 503 until it has. 404 when a node is not there."
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
    if not steps_built(store):
        logger.warning("The steps are not built yet: run `semantic graph-steps`.")
        raise HTTPException(
            status_code=503,
            detail="The chains are not searchable yet. Try again later.",
            headers={"Retry-After": "3600"},
        )
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
                        weight=step.weight,
                    )
                    for step in chain.steps
                ],
            )
            for chain in block.chains
        ],
    )
