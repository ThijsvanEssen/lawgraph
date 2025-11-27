from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_article_citations, get_article_with_relations
from lawgraph.api.schemas import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleDetailResponse,
    ArticleSummaryDTO,
    InstrumentSummaryDTO,
    JudgmentSummaryDTO,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

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
async def get_article_detail(
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


def _build_article_citation_target(doc: dict[str, Any]) -> ArticleCitationTarget:
    props = doc.get("props") or {}
    collection = doc["_id"].split("/", 1)[0] if "/" in doc["_id"] else doc["_id"]
    return ArticleCitationTarget(
        id=doc["_id"],
        key=doc["_key"],
        collection=collection,
        bwb_id=props.get("bwb_id"),
        article_number=props.get("article_number"),
        display_name=props.get("display_name"),
    )
