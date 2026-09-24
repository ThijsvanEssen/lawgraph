from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleRelationDTO,
    JudgmentSummaryDTO,
)
from lawgraph.api.schemas.judgments import (
    JudgmentCitedArticle,
    JudgmentDetailResponse,
    JudgmentDTO,
    JudgmentListItemDTO,
    JudgmentListResponse,
    mentions_of,
)
from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore
from lawgraph.db.queries.judgments import (
    JudgmentArticleRelation,
    get_judgment_with_relations,
    get_judgments_list,
)

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "",
    response_model=JudgmentListResponse,
    summary="Paginated list of judgments",
    description=(
        "A paginated list of judgments with filters on court (the ECLI court "
        "code), tier (hoge_raad / gerechtshof / rechtbank / bijzonder), date "
        "range and a minimum citation count."
    ),
    tags=["judgments"],
)
def list_judgments(
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[
        str | None, Query(description="Free-text over display_name/ecli/summary")
    ] = None,
    court: Annotated[
        str | None,
        Query(description="ECLI court code, e.g. 'HR', 'RBAMS', 'GHARL'"),
    ] = None,
    tier: Annotated[
        Literal["hoge_raad", "gerechtshof", "rechtbank", "bijzonder"] | None,
        Query(),
    ] = None,
    source: Annotated[
        str | None,
        Query(description="Filter op bron, e.g. 'rechtspraak', 'echr', 'cjeu'"),
    ] = None,
    date_from: Annotated[
        str | None,
        Query(alias="from", description="Lower bound on judgment date, YYYY-MM-DD"),
    ] = None,
    date_to: Annotated[
        str | None,
        Query(alias="to", description="Upper bound on judgment date, YYYY-MM-DD"),
    ] = None,
    cited_by_min: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[
        Literal["date_desc", "date_asc", "citation_count"], Query()
    ] = "date_desc",
) -> JudgmentListResponse:
    data = get_judgments_list(
        store,
        q=q,
        court=court,
        tier=tier,
        source=source,
        date_from=date_from,
        date_to=date_to,
        cited_by_min=cited_by_min,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items = [JudgmentListItemDTO.from_document(row) for row in data.get("items", [])]
    return JudgmentListResponse(items=items, total=int(data.get("total", 0)))


@router.get(
    "/{ecli}",
    response_model=JudgmentDetailResponse,
    summary="One judgment with the articles it cites",
    description=(
        "Looks a judgment up by ECLI, follows its REFERS_TO edges to articles "
        "and adds each article with its parent instrument."
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
    cited_articles = [
        JudgmentCitedArticle.from_relation(article, rel.meta, rel.confidence)
        for article, rel in zip(articles, data.articles, strict=True)
    ]

    judgment = JudgmentDTO.from_document(data.judgment)
    citations = _citations_by_paragraph(data.articles)
    judgment = judgment.model_copy(
        update={
            "paragraphs": [
                paragraph.model_copy(
                    update={"citations": citations.get(paragraph.paragraph_id, [])}
                )
                for paragraph in judgment.paragraphs
            ]
        }
    )

    cited_judgments = [
        JudgmentSummaryDTO.from_document(doc) for doc in data.cited_judgments
    ]

    return JudgmentDetailResponse(
        judgment=judgment,
        articles=articles,
        cited_articles=cited_articles,
        cited_judgments=cited_judgments,
        series=[JudgmentSummaryDTO.from_document(doc) for doc in data.series],
        metadata=data.metadata or None,
    )


def _citations_by_paragraph(
    relations: list[JudgmentArticleRelation],
) -> dict[str, list[ArticleCitationSpan]]:
    """The stored mentions of every cited article, as the citation spans of their paragraph.

    Detected when the judgment was linked (``semantic rechtspraak``), so serving one costs
    no detection.
    """
    spans: dict[str, list[ArticleCitationSpan]] = {}
    for relation in relations:
        props = relation.article.get("props") or {}
        target = ArticleCitationTarget(
            id=relation.article["_id"],
            key=relation.article["_key"],
            collection=COLLECTION_ARTICLES,
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name"),
        )
        for mention in mentions_of(relation.meta):
            spans.setdefault(mention.paragraph_id, []).append(
                ArticleCitationSpan(
                    start=mention.start,
                    end=mention.end,
                    text=mention.raw_match,
                    target=target,
                    confidence=mention.confidence,
                    **mention.parts.to_dict(),
                )
            )
    for paragraph_spans in spans.values():
        paragraph_spans.sort(key=lambda span: span.start or 0)
    return spans
