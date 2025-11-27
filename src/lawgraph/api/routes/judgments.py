from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_judgment_with_relations
from lawgraph.api.schemas import ArticleRelationDTO, JudgmentDetailResponse, JudgmentDTO
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/{ecli}",
    response_model=JudgmentDetailResponse,
    summary="Haal een uitspraak met gelinkte artikelen",
    description=(
        "Zoekt een uitspraak op via ECLI, leest de semantische `MENTIONS_ARTICLE`-edges "
        "en voegt elke gevonden artikel-/instrumentcombinatie toe."
    ),
    tags=["judgments"],
)
async def get_judgment_detail(
    ecli: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> JudgmentDetailResponse:
    """Return a judgment plus the articles it mentions."""
    try:
        data = get_judgment_with_relations(store, ecli)
    except ValueError as err:
        logger.debug("Judgment %s not found", ecli)
        raise HTTPException(status_code=404, detail="Judgment not found") from err

    articles = [
        ArticleRelationDTO.from_documents(rel.article, rel.instrument)
        for rel in data.articles
    ]

    return JudgmentDetailResponse(
        judgment=JudgmentDTO.from_document(data.judgment),
        articles=articles,
        metadata=data.metadata or None,
    )
