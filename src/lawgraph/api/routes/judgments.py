from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_judgment_with_relations, get_judgments_list
from lawgraph.api.schemas import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleRelationDTO,
    JudgmentDetailResponse,
    JudgmentDTO,
    JudgmentListItemDTO,
    JudgmentListResponse,
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
    "",
    response_model=JudgmentListResponse,
    summary="Gepagineerde lijst van uitspraken",
    description=(
        "Gepagineerde lijst van uitspraken (arresten) met filters op court (ECLI-code), "
        "tier (hoge_raad/gerechtshof/rechtbank/bijzonder), datumbereik en citatiedrempel."
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
    items = [JudgmentListItemDTO.from_row(row) for row in data.get("items", [])]
    return JudgmentListResponse(items=items, total=int(data.get("total", 0)))


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
    """Add inline article citation spans to each paragraph.

    All article lookups are batched into a single AQL query so we pay one
    round-trip for the whole judgment instead of one per citation hit.
    """
    # First pass: collect all hits across all paragraphs.
    para_hits: list[tuple[JudgmentParagraph, list]] = []
    all_keys: list[str] = []
    for para in paragraphs:
        hits = detect_article_references(para.text, _ARTICLE_CODE_MAPPING)
        valid = [h for h in hits if h.bwb_id]
        para_hits.append((para, valid))
        for h in valid:
            all_keys.append(make_node_key(h.bwb_id, h.article_number))

    if not all_keys:
        return list(paragraphs)

    # Single bulk fetch for all referenced article keys.
    aql = f"""
    FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
        FILTER doc._key IN @keys
        RETURN doc
    """
    article_by_key = {
        doc["_key"]: doc for doc in store.query(aql, {"keys": list(set(all_keys))})
    }

    # Second pass: build enriched paragraphs.
    result: list[JudgmentParagraph] = []
    for para, hits in para_hits:
        citaties: list[ArticleCitationSpan] = []
        for hit in hits:
            article_key = make_node_key(hit.bwb_id, hit.article_number)
            doc = article_by_key.get(article_key)
            if doc is None:
                continue
            props = doc.get("props") or {}
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
                        id=doc["_id"],
                        key=doc["_key"],
                        collection=COLLECTION_INSTRUMENT_ARTICLES,
                        bwb_id=props.get("bwb_id"),
                        article_number=props.get("article_number"),
                        display_name=props.get("display_name"),
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
