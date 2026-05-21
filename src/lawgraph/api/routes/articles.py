from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_article_citations,
    get_article_in_flux,
    get_article_legislative_history,
    get_article_with_relations,
)
from lawgraph.api.schemas import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleDetailResponse,
    ArticleInFluxResponse,
    ArticleLegislativeHistoryResponse,
    ArticleSummaryDTO,
    InstrumentSummaryDTO,
    JudgmentSummaryDTO,
    LegislativeHistoryEntry,
)
from lawgraph.config.constants import COLLECTION_INSTRUMENT_ARTICLES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import make_node_key, parse_arango_id
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/{bwb_id}/{article_number}",
    response_model=ArticleDetailResponse,
    summary="Haal een BWB-artikel plus interne verwijzingen op",
    description=(
        "Zoekt een `instrument_article` op basis van `bwb_id` en `article_number`, "
        "voegt het parent-instrument toe, levert alle uitspraken die het artikel noemen "
        "via semantische edges en voegt extra artikelverwijzingen uit de tekst toe."
    ),
    tags=["articles"],
)
def get_article_detail(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleDetailResponse:
    """Return an article plus its instrument and mentioning judgments."""
    try:
        data = get_article_with_relations(store, bwb_id, article_number)
    except ValueError as err:
        logger.debug("Article %s %s not found", bwb_id, article_number)
        raise HTTPException(status_code=404, detail="Article not found") from err

    instrument = (
        InstrumentSummaryDTO.from_document(data.instrument)
        if data.instrument is not None
        else None
    )

    judgments = [JudgmentSummaryDTO.from_document(doc) for doc in data.judgments]
    citation_entries = get_article_citations(store, data.article)
    citations = [
        ArticleCitationSpan(
            start=entry.start,
            end=entry.end,
            text=entry.text,
            target=_build_article_citation_target(entry.target),
            confidence=entry.confidence,
        )
        for entry in citation_entries
    ]

    return ArticleDetailResponse(
        article=ArticleSummaryDTO.from_document(data.article),
        instrument=instrument,
        judgments=judgments,
        citations=citations,
        metadata=data.metadata or None,
    )


@router.get(
    "/{bwb_id}/{article_number}/legislative-history",
    response_model=ArticleLegislativeHistoryResponse,
    summary="Wetgevingsgeschiedenis van een artikel",
    description=(
        "Geeft alle dossiers en documenten terug die dit artikel hebben ingevoerd, "
        "gewijzigd of voortaan willen wijzigen. Bevat zowel canonieke als voorgestelde "
        "wijzigingen (status='voorgesteld'). Retourneert een lege lijst als er geen "
        "geschiedenis is — nooit een 404."
    ),
    tags=["articles"],
)
def get_legislative_history(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleLegislativeHistoryResponse:
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"{COLLECTION_INSTRUMENT_ARTICLES}/{article_key}"
    raw_entries = get_article_legislative_history(store, bwb_id, article_number)
    entries = [LegislativeHistoryEntry(**e) for e in raw_entries]
    return ArticleLegislativeHistoryResponse(
        article_id=article_id,
        entries=entries,
        total=len(entries),
    )


@router.get(
    "/{bwb_id}/{article_number}/in-flux",
    response_model=ArticleInFluxResponse,
    summary="In-flux status van een artikel",
    description=(
        "Goedkope check of dit artikel momenteel doelwit is van een of meer open "
        "wetsvoorstellen. Retourneert een boolean en het aantal open dossiers. "
        "Agressief gecached — altijd 200, nooit 404."
    ),
    tags=["articles"],
)
def get_in_flux(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleInFluxResponse:
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"{COLLECTION_INSTRUMENT_ARTICLES}/{article_key}"
    result = get_article_in_flux(store, bwb_id, article_number)
    return ArticleInFluxResponse(
        article_id=article_id,
        in_flux=result.get("in_flux", False),
        open_dossier_count=result.get("open_dossier_count", 0),
    )


def _build_article_citation_target(doc: dict[str, Any]) -> ArticleCitationTarget:
    props = doc.get("props") or {}
    collection = parse_arango_id(doc["_id"])[0]
    return ArticleCitationTarget(
        id=doc["_id"],
        key=doc["_key"],
        collection=collection,
        bwb_id=props.get("bwb_id"),
        article_number=props.get("article_number"),
        display_name=props.get("display_name"),
    )
