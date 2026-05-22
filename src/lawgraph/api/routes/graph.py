from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from lawgraph.api.cache import _MISSING, TTLCache
from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_global_graph,
    get_instrument_layer_graph,
    get_judgment_graph,
)
from lawgraph.api.schemas import (
    ArticleGraphNodeDTO,
    GlobalGraphResponse,
    GraphEdgeDTO,
    InstrumentEdgeDTO,
    InstrumentLayerGraphResponse,
    InstrumentLayerInstrumentDTO,
    JudgmentGraphNodeDTO,
    JudgmentLayerGraphResponse,
)
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

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
    summary="Volledig globaal graph — alle nodes en edges zonder instrumentfilter",
    description=(
        "Geeft alle instrumenten, artikelen, uitspraken en edges terug, "
        "inclusief nodes die niet aan een instrument zijn gekoppeld. "
        "Gebruik `include_judgments=false` om uitspraken weg te laten."
    ),
    tags=["graph"],
)
def get_global_graph_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    include_judgments: Annotated[
        bool, Query(description="Voeg uitspraken toe aan het graph")
    ] = True,
    max_judgments: Annotated[
        int, Query(ge=1, le=5000, description="Maximaal aantal uitspraken")
    ] = 500,
) -> GlobalGraphResponse:
    cache_key = f"global:j={int(include_judgments)}:n={max_judgments}"
    cached = _layer_cache.get(cache_key)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]

    data = get_global_graph(
        store,
        include_judgments=include_judgments,
        max_judgments=max_judgments,
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
    summary="Wet-niveau graph — instrumenten als knopen met geaggregeerde citatie-edges",
    description=(
        "Geeft alle instrumenten (NL en EU) terug als knopen, met edges tussen instrumenten die "
        "gebaseerd zijn op geaggregeerde artikel-niveau citaties (`verwijst_naar`, gewogen) "
        "en directe `implementeert`-edges (IMPLEMENTS_DIRECTIVE). "
        "Gebruik dit voor de 'layer view' waarbij elke knoop een volledige wet vertegenwoordigt."
    ),
    tags=["graph"],
)
def get_instrument_layer_graph_route(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentLayerGraphResponse:
    cached = _layer_cache.get("instrument_layer")
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]

    data = get_instrument_layer_graph(store)

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
    _layer_cache.set("instrument_layer", response)
    return response


@router.get(
    "/judgments",
    response_model=JudgmentLayerGraphResponse,
    summary="Uitspraak-niveau graph — uitspraken als knopen met citatie-edges",
    description=(
        "Geeft alle geladen uitspraken terug als knopen, met twee soorten edges:\n\n"
        "- **`citeert`** — uitspraak → uitspraak (CITES_JUDGMENT, weight=1)\n"
        "- **`citeert_wet`** — uitspraak → instrument, geaggregeerd vanuit CITES_ARTICLE "
        "(weight = aantal unieke geciteerde artikelen in dat instrument)\n\n"
        "De wetnodes zijn de instrumenten die door de uitspraken worden geciteerd — "
        "handig als ankerpunten in de visualisatie. "
        "Gebruik `max_judgments` om de omvang te beperken; standaard 1000."
    ),
    tags=["graph"],
)
def get_judgment_graph_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    max_judgments: Annotated[
        int,
        Query(ge=1, le=10000, description="Maximaal aantal uitspraken"),
    ] = 1000,
    include_stubs: Annotated[
        bool,
        Query(description="Voeg stub-uitspraken toe (nog niet geladen)"),
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
