from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_article_with_relations
from lawgraph.api.schemas import (
    ArticleDTO,
    ArticleDetailResponse,
    InstrumentDTO,
    JudgmentSummaryDTO,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)



@router.get("/{bwb_id}/{article_number}", response_model=ArticleDetailResponse)
async def get_article_detail(
    bwb_id: str,
    article_number: str,
    store: ArangoStore = Depends(get_store),
) -> ArticleDetailResponse:
    """Return an article plus its instrument and mentioning judgments."""
    try:
        data = get_article_with_relations(store, bwb_id, article_number)
    except ValueError:
        logger.debug("Article %s %s not found", bwb_id, article_number)
        raise HTTPException(status_code=404, detail="Article not found")

    instrument = (
        InstrumentDTO.from_document(data.instrument)
        if data.instrument is not None
        else None
    )

    judgments = [JudgmentSummaryDTO.from_document(doc) for doc in data.judgments]

    return ArticleDetailResponse(
        article=ArticleDTO.from_document(data.article),
        instrument=instrument,
        judgments=judgments,
        metadata=data.metadata or None,
    )
