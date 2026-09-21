from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.articles import (
    get_article_citations,
    get_article_history,
    get_article_in_flux,
    get_article_legislative_history,
    get_article_with_relations,
)
from lawgraph.api.queries.relationships import get_article_relationship_data
from lawgraph.api.schemas.articles import (
    ArticleDetailResponse,
    ArticleHistoryResponse,
    ArticleInFluxResponse,
    ArticleLegislativeHistoryResponse,
    ArticleRelationshipsResponse,
    ArticleRelationshipWithType,
    ArticleSummaryDTO,
    ArticleVersionDTO,
    LegislativeHistoryEntry,
    ScopeArticleReference,
    references_from_props,
)
from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    InstrumentSummaryDTO,
    JudgmentSummaryDTO,
)
from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import make_node_key, parse_arango_id
from lawgraph.db import ArangoStore

router = APIRouter()
logger = get_logger(__name__)


@router.get(
    "/{bwb_id}/{article_number}",
    response_model=ArticleDetailResponse,
    summary="One article with its references",
    description=(
        "Looks up an article by `bwb_id` and `article_number`, adds its parent "
        "instrument and every judgment that cites it, plus the article "
        "references recorded on the article itself."
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
            reference_kind=entry.reference_kind,
            confidence=entry.confidence,
            **entry.qualifier.to_dict(),
        )
        for entry in citation_entries
    ]

    relationship_data = get_article_relationship_data(store, data.article["_id"])
    upstream, downstream, scope = _build_relationship_dtos(relationship_data)

    return ArticleDetailResponse(
        article=ArticleSummaryDTO.from_document(data.article),
        instrument=instrument,
        judgments=judgments,
        citations=citations,
        references=references_from_props(data.article.get("props") or {}),
        metadata=data.metadata or None,
        upstream_dependencies=upstream,
        downstream_implications=downstream,
        scope_articles=scope,
    )


def _build_relationship_dtos(
    relationship_data: dict[str, list[dict[str, Any]]],
) -> tuple[
    list[ArticleRelationshipWithType],
    list[ArticleRelationshipWithType],
    list[ScopeArticleReference],
]:
    upstream = [
        ArticleRelationshipWithType.from_row(row)
        for row in relationship_data.get("upstream", [])
    ]
    downstream = [
        ArticleRelationshipWithType.from_row(row)
        for row in relationship_data.get("downstream", [])
    ]
    scope = [
        ScopeArticleReference.from_row(row)
        for row in relationship_data.get("scope", [])
    ]
    return upstream, downstream, scope


@router.get(
    "/{bwb_id}/{article_number}/relationships",
    response_model=ArticleRelationshipsResponse,
    summary="Semantic relationships of an article",
    description=(
        "Upstream dependencies (outgoing references), downstream implications "
        "(incoming references) and annex scopes, each with its semantic type, "
        "explanation, expert badge and community votes."
    ),
    tags=["articles"],
)
def get_article_relationships(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleRelationshipsResponse:
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"{COLLECTION_ARTICLES}/{article_key}"
    relationship_data = get_article_relationship_data(store, article_id)
    upstream, downstream, scope = _build_relationship_dtos(relationship_data)
    return ArticleRelationshipsResponse(
        article_id=article_id,
        upstream_dependencies=upstream,
        downstream_implications=downstream,
        scope_articles=scope,
    )


@router.get(
    "/{bwb_id}/{article_number}/history",
    response_model=ArticleHistoryResponse,
    summary="Version history of an article",
    description=(
        "Every version of one article, identified by the stable BWB `stam_id` so "
        "renumbering does not break the chain, oldest first. Each version carries "
        "its validity period, text, the kind of change (`change`: introduces / "
        "amends / repeals), the amending publication (`amended_by`) and the "
        "commencement publication (`commencement`) with their dossiers. "
        "404 when the article is unknown."
    ),
    tags=["articles"],
)
def get_article_version_history(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleHistoryResponse:
    try:
        data = get_article_history(store, bwb_id, article_number)
    except ValueError as err:
        logger.debug("Article %s %s not found", bwb_id, article_number)
        raise HTTPException(status_code=404, detail="Article not found") from err
    props = data.article.get("props") or {}
    return ArticleHistoryResponse(
        bwb_id=props.get("bwb_id") or bwb_id,
        article_number=article_number,
        stam_id=props.get("stam_id"),
        versions=[
            ArticleVersionDTO.from_document(doc, data.dossier_titles)
            for doc in data.versions
        ],
    )


@router.get(
    "/{bwb_id}/{article_number}/legislative-history",
    response_model=ArticleLegislativeHistoryResponse,
    summary="Legislative history of an article",
    description=(
        "Every dossier and document that introduced, changed or proposes to "
        "change this article, covering both enacted (`canoniek`) and proposed "
        "(`voorgesteld`) changes. Returns an empty list when there is no "
        "history — never a 404."
    ),
    tags=["articles"],
)
def get_legislative_history(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleLegislativeHistoryResponse:
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"{COLLECTION_ARTICLES}/{article_key}"
    raw_entries = get_article_legislative_history(
        store, bwb_id, article_number, article_id=article_id
    )
    entries = [LegislativeHistoryEntry(**e) for e in raw_entries]
    return ArticleLegislativeHistoryResponse(
        article_id=article_id,
        entries=entries,
        total=len(entries),
    )


@router.get(
    "/{bwb_id}/{article_number}/in-flux",
    response_model=ArticleInFluxResponse,
    summary="In-flux status of an article",
    description=(
        "A cheap check whether one or more open bills currently target this "
        "article. Returns a flag and the number of open dossiers. Aggressively "
        "cached — always 200, never 404."
    ),
    tags=["articles"],
)
def get_in_flux(
    bwb_id: str,
    article_number: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ArticleInFluxResponse:
    article_key = make_node_key(bwb_id, article_number)
    article_id = f"{COLLECTION_ARTICLES}/{article_key}"
    result = get_article_in_flux(store, bwb_id, article_number, article_id=article_id)
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
