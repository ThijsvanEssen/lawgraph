from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import parse_choices
from lawgraph.api.schemas.graph import (
    ArticleGraphNodeDTO,
    GlobalGraphResponse,
    GraphEdgeDTO,
    InstrumentEdgeDTO,
    InstrumentLayerGraphResponse,
    InstrumentLayerInstrumentDTO,
    JudgmentGraphNodeDTO,
    JudgmentLayerGraphResponse,
)
from lawgraph.core.cache import _MISSING, TTLCache
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore
from lawgraph.db.queries.graph import (
    GLOBAL_GRAPH_NODE_TYPES,
    GLOBAL_GRAPH_RELATIONS,
    INSTRUMENT_LAYER_RELATIONS,
    get_global_graph,
    get_instrument_layer_graph,
    get_judgment_graph,
)

router = APIRouter()
logger = get_logger(__name__)

# Layer-graph endpoints aggregate citation edges across the whole corpus —
# the underlying AQL takes ~250 ms even with the article-id→bwb_id MERGE
# trick. The result is a slow-moving analytic signal (it only changes when
# the semantic pipeline writes new edges, which happens on the backfill/
# normalize schedule). A short TTL cache means the heavy AQL fires at most
# once a minute regardless of viewer concurrency.
_layer_cache: TTLCache[str, Any] = TTLCache(maxsize=16, ttl=60.0)


@router.get(
    "/global",
    response_model=GlobalGraphResponse,
    summary="Whole graph — every node and edge, no instrument filter",
    description=(
        "Every instrument, article, judgment and edge, including nodes that "
        "hang off no instrument. `node_types` (`instrument`, `article`, "
        "`judgment`; default all three) says which nodes to load and `relations` "
        "(`REFERS_TO`, `EXPLAINS`, `PART_OF`, `IMPLEMENTS`, `AMENDS`; default all "
        "five) which edges to keep between them."
    ),
    tags=["graph"],
)
def get_global_graph_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    node_types: Annotated[
        str | None,
        Query(description="Comma-separated node types to load."),
    ] = None,
    relations: Annotated[
        str | None,
        Query(description="Comma-separated relations to keep."),
    ] = None,
    max_judgments: Annotated[
        int, Query(ge=1, le=5000, description="Maximum number of judgments")
    ] = 500,
) -> GlobalGraphResponse:
    types = (
        parse_choices(node_types, GLOBAL_GRAPH_NODE_TYPES, "node_types")
        or GLOBAL_GRAPH_NODE_TYPES
    )
    kinds = (
        parse_choices(relations, GLOBAL_GRAPH_RELATIONS, "relations")
        or GLOBAL_GRAPH_RELATIONS
    )
    cache_key = f"global:t={','.join(types)}:r={','.join(kinds)}:n={max_judgments}"
    cached = _layer_cache.get(cache_key)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]

    data = get_global_graph(
        store, node_types=types, relations=kinds, max_judgments=max_judgments
    )

    edges = [
        GraphEdgeDTO(
            from_id=e.from_id,
            to_id=e.to_id,
            relation_type=e.relation_type,
            start=e.start,
            end=e.end,
            text=e.text,
            confidence=e.confidence,
        )
        for e in data.edges
    ]

    response = GlobalGraphResponse(
        instruments=[
            InstrumentLayerInstrumentDTO.from_document(doc) for doc in data.instruments
        ],
        articles=[ArticleGraphNodeDTO.from_document(doc) for doc in data.articles],
        judgments=[JudgmentGraphNodeDTO.from_document(doc) for doc in data.judgments],
        edges=edges,
        metadata=data.metadata,
    )
    _layer_cache.set(cache_key, response)
    return response


@router.get(
    "/instruments",
    response_model=InstrumentLayerGraphResponse,
    summary="Instrument-level graph — instruments as nodes with aggregated edges",
    description=(
        "Every instrument (NL and EU) as a node, with edges between instruments "
        "aggregated from article-level references (REFERS_TO, weighted) plus "
        "the direct IMPLEMENTS and AMENDS edges. Use this for the layer view, "
        "where each node stands for a whole law. `relations` (`REFERS_TO`, "
        "`IMPLEMENTS`, `AMENDS`; default all three) says which edges to return."
    ),
    tags=["graph"],
)
def get_instrument_layer_graph_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    relations: Annotated[
        str | None,
        Query(description="Comma-separated relations to keep."),
    ] = None,
) -> InstrumentLayerGraphResponse:
    kinds = (
        parse_choices(relations, INSTRUMENT_LAYER_RELATIONS, "relations")
        or INSTRUMENT_LAYER_RELATIONS
    )
    cache_key = f"instrument_layer:r={','.join(kinds)}"
    cached = _layer_cache.get(cache_key)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]

    data = get_instrument_layer_graph(store, relations=kinds)

    edges = [
        InstrumentEdgeDTO(
            from_id=e.from_id,
            to_id=e.to_id,
            relation_type=e.relation_type,
            weight=e.weight,
            confidence=e.confidence,
        )
        for e in data.edges
    ]

    response = InstrumentLayerGraphResponse(
        instruments=[
            InstrumentLayerInstrumentDTO.from_document(
                doc, stats=data.stats.get(doc["_id"])
            )
            for doc in data.instruments
        ],
        edges=edges,
        metadata=data.metadata,
    )
    _layer_cache.set(cache_key, response)
    return response


@router.get(
    "/judgments",
    response_model=JudgmentLayerGraphResponse,
    summary="Judgment-level graph — judgments as nodes with citation edges",
    description=(
        "Every loaded judgment as a node, with REFERS_TO edges to the "
        "instruments it cites, aggregated from the article-level references "
        "(weight = number of distinct articles cited in that instrument).\n\n"
        "The instrument nodes are the instruments the judgments cite — useful "
        "as anchor points in the visualisation. Use `max_judgments` to bound "
        "the size; the default is 1000."
    ),
    tags=["graph"],
)
def get_judgment_graph_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    max_judgments: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximum number of judgments"),
    ] = 1000,
    include_stubs: Annotated[
        bool,
        Query(description="Include stub judgments (not yet loaded)"),
    ] = False,
) -> JudgmentLayerGraphResponse:
    cache_key = f"judgment_layer:n={max_judgments}:stubs={int(include_stubs)}"
    cached = _layer_cache.get(cache_key)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]

    data = get_judgment_graph(
        store,
        max_judgments=max_judgments,
        include_stubs=include_stubs,
    )
    edges = [
        InstrumentEdgeDTO(
            from_id=e.from_id,
            to_id=e.to_id,
            relation_type=e.relation_type,
            weight=e.weight,
            confidence=e.confidence,
        )
        for e in data.edges
    ]
    response = JudgmentLayerGraphResponse(
        judgments=[JudgmentGraphNodeDTO.from_document(doc) for doc in data.judgments],
        instruments=[
            InstrumentLayerInstrumentDTO.from_document(doc) for doc in data.instruments
        ],
        edges=edges,
        metadata=data.metadata,
    )
    _layer_cache.set(cache_key, response)
    return response
