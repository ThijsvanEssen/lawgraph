from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_judgment_with_relations
from lawgraph.api.schemas import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleRelationDTO,
    JudgmentDetailResponse,
    JudgmentDTO,
    JudgmentParagraph,
    JudgmentSummaryDTO,
)
from lawgraph.config.settings import COLLECTION_INSTRUMENT_ARTICLES
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import make_node_key
from lawgraph.pipelines.semantic.rechtspraak_articles import detect_article_references

router = APIRouter()
logger = get_logger(__name__)

# Maps citation aliases to BWB identifiers for inline citation detection.
_ARTICLE_CODE_MAPPING: dict[str, str] = {
    "Sr": "BWBR0001854",
    "Sv": "BWBR0001903",
    "WVW": "BWBR0006622",
}


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
def get_judgment_detail(
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

    judgment = JudgmentDTO.from_document(data.judgment)
    if judgment.paragraphs:
        judgment = judgment.model_copy(
            update={"paragraphs": _enrich_paragraphs(judgment.paragraphs, store)}
        )

    cited_judgments = [
        JudgmentSummaryDTO.from_document(doc) for doc in data.cited_judgments
    ]

    return JudgmentDetailResponse(
        judgment=judgment,
        articles=articles,
        cited_judgments=cited_judgments,
        metadata=data.metadata or None,
    )


def _enrich_paragraphs(
    paragraphs: list[JudgmentParagraph],
    store: ArangoStore,
) -> list[JudgmentParagraph]:
    """Add inline article citation spans to each paragraph."""
    result: list[JudgmentParagraph] = []
    for para in paragraphs:
        hits = detect_article_references(para.text, _ARTICLE_CODE_MAPPING)
        citaties: list[ArticleCitationSpan] = []
        for hit in hits:
            if not hit.bwb_id:
                continue
            article_key = make_node_key(hit.bwb_id, hit.article_number)
            article_node = store.get_node(COLLECTION_INSTRUMENT_ARTICLES, article_key)
            if article_node is None:
                continue
            start: int | None = None
            end: int | None = None
            if hit.raw_match:
                pos = para.text.find(hit.raw_match)
                if pos >= 0:
                    start = pos
                    end = pos + len(hit.raw_match)
            citaties.append(
                ArticleCitationSpan(
                    start=start,
                    end=end,
                    text=hit.raw_match,
                    target=ArticleCitationTarget(
                        id=article_node.id or "",
                        key=article_node.key or "",
                        collection=article_node.collection,
                        bwb_id=article_node.props.get("bwb_id"),
                        article_number=article_node.props.get("article_number"),
                        display_name=article_node.props.get("display_name"),
                    ),
                    confidence=hit.confidence,
                )
            )
        result.append(
            JudgmentParagraph(
                number=para.number, kind=para.kind, text=para.text, citaties=citaties
            )
        )
    return result
