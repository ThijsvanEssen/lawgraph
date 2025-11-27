from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_article_with_relations
from lawgraph.api.schemas import (
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
    summary="Haal een BWB-artikel met draaiende instrumenten en uitspraken op",
    description=(
        "Zoekt een `instrument_article` op basis van `bwb_id` en `article_number`, "
        "voegt het parent-instrument toe en levert alle uitspraken die het artikel noemen "
        "via de semantische `MENTIONS_ARTICLE`-edges."
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

    return ArticleDetailResponse(
        article=ArticleSummaryDTO.from_document(data.article),
        instrument=instrument,
        judgments=judgments,
        metadata=data.metadata or None,
    )
