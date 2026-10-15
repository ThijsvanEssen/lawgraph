from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import CourtKind, Tier, iso_day
from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleCitationTarget,
    ArticleRelationDTO,
    JudgmentSummaryDTO,
)
from lawgraph.api.schemas.judgments import (
    JudgmentCitedArticle,
    JudgmentCitedJudgment,
    JudgmentConclusionDTO,
    JudgmentDetailResponse,
    JudgmentDTO,
    JudgmentFacets,
    JudgmentListItemDTO,
    JudgmentListResponse,
    RelatedJudgmentDTO,
    mentions_of,
)
from lawgraph.core.mentions import mention_texts
from lawgraph.db import GraphStore
from lawgraph.db.queries.judgments import (
    JudgmentArticleRelation,
    JudgmentFilters,
    get_judgment_with_relations,
    get_judgments_list,
)

router = APIRouter()


@router.get(
    "",
    response_model=JudgmentListResponse,
    summary="Paginated list of judgments",
    description=(
        "A paginated list of judgments with filters on court (the ECLI court "
        "code), tier (the Type of the court in the Instanties value list of the "
        "Rechtspraak: hoge_raad, raad_van_state, gerechtshof, rechtbank, tuchtcollege, "
        "andere_instantie, koninkrijksinstantie, …), court_kind (the kind of court "
        "within the tier: ambtenarengerecht, raad_van_beroep, gerecht_in_eerste_aanleg, "
        "…), area of law (`subject`), source, date range and a minimum citation count. "
        "`facets` counts the judgments under the filters per `tier` (without the tier "
        "and court_kind filters), per `court_kind` (without its own filter), per "
        "`source` (without the source filter), per year of `date` (without `from` "
        "and `to`), per area of law (`subjects`, without `subject`) and per `procedure` "
        "(without its filter). `facets=false` leaves them out (null): the pages after the "
        "first need none."
    ),
    tags=["judgments"],
)
def list_judgments(
    store: Annotated[GraphStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    facets: Annotated[
        bool, Query(description="Count per tier, court kind, source, year, area.")
    ] = True,
    q: Annotated[
        str | None, Query(description="Free-text over display_name/ecli/summary")
    ] = None,
    court: Annotated[
        str | None,
        Query(description="ECLI court code, e.g. 'HR', 'RBAMS', 'GHARL'"),
    ] = None,
    tier: Annotated[
        Tier | None,
        Query(
            description="The tier: `hoge_raad`, `gerechtshof`, `andere_instantie`, …"
        ),
    ] = None,
    court_kind: Annotated[
        CourtKind | None,
        Query(
            description="The kind of court: `ambtenarengerecht`, `raad_van_beroep`, "
            "`hoge_raad`, …"
        ),
    ] = None,
    source: Annotated[
        str | None,
        Query(description="The source, e.g. 'rechtspraak', 'echr'."),
    ] = None,
    date_from: Annotated[
        dt.date | None,
        Query(alias="from", description="Lower bound on judgment date, YYYY-MM-DD"),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Upper bound on judgment date, YYYY-MM-DD"),
    ] = None,
    subject: Annotated[
        str | None,
        Query(
            description="An area of law, one of `subjects` as written: `Strafrecht`, "
            "`Bestuursrecht; Belastingrecht`."
        ),
    ] = None,
    subject_area: Annotated[
        str | None,
        Query(
            description="A main area of law: the judgments with a subject in it, "
            "`Bestuursrecht` for `Bestuursrecht` and `Bestuursrecht; Belastingrecht` alike "
            "(the part of a subject before its first `;`)."
        ),
    ] = None,
    procedure: Annotated[
        str | None,
        Query(
            description="The procedure, as the source writes it (Rechtspraak "
            "`psi:procedure`): `Hoger beroep`, `Cassatie`, `Eerste aanleg - meervoudig`."
        ),
    ] = None,
    cited_by_min: Annotated[int | None, Query(ge=0)] = None,
    include_stubs: Annotated[
        bool,
        Query(
            description="Also the judgments known only because something cites them "
            "(no date, court or text)."
        ),
    ] = False,
    sort: Annotated[
        Literal["date_desc", "date_asc", "citation_count"], Query()
    ] = "date_desc",
) -> JudgmentListResponse:
    filters = JudgmentFilters(
        q=q,
        court=court,
        tier=tier.value if tier else None,
        court_kind=court_kind.value if court_kind else None,
        source=source,
        subject=(subject or "").strip() or None,
        subject_area=(subject_area or "").strip() or None,
        procedure=(procedure or "").strip() or None,
        from_date=iso_day(date_from),
        to_date=iso_day(date_to),
        cited_by_min=cited_by_min,
        include_stubs=include_stubs,
    )
    data = get_judgments_list(
        store, filters, sort=sort, limit=limit, offset=offset, facets=facets
    )
    items = [JudgmentListItemDTO.from_document(row) for row in data.get("items", [])]
    return JudgmentListResponse(
        items=items,
        total=int(data.get("total", 0)),
        facets=JudgmentFacets(**(data.get("facets") or {})) if facets else None,
    )


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
    store: Annotated[GraphStore, Depends(get_store)],
) -> JudgmentDetailResponse:
    """Return a judgment plus the articles it mentions."""
    data = get_judgment_with_relations(store, ecli)

    articles = [
        ArticleRelationDTO.from_documents(rel.article, rel.instrument)
        for rel in data.articles
    ]
    props = data.judgment.get("props") or {}
    texts = mention_texts(props.get("paragraphs") or [], props.get("footnotes") or [])
    cited_articles = [
        JudgmentCitedArticle.from_relation(article, rel.meta, rel.confidence, texts)
        for article, rel in zip(articles, data.articles, strict=True)
    ]

    judgment = JudgmentDTO.from_document(data.judgment)
    spans = _citation_spans(data.articles, data.cited_judgments)
    judgment = judgment.model_copy(
        update={
            "paragraphs": [
                paragraph.model_copy(
                    update={"citations": spans.get((paragraph.paragraph_id, None), [])}
                )
                for paragraph in judgment.paragraphs
            ],
            "footnotes": [
                note.model_copy(
                    update={
                        "citations": spans.get(
                            (note.paragraph_id or f"fn-{note.label}", note.label), []
                        )
                    }
                )
                for note in judgment.footnotes
            ],
        }
    )

    cited_judgments = [
        JudgmentCitedJudgment.from_citation(doc, texts) for doc in data.cited_judgments
    ]

    return JudgmentDetailResponse(
        judgment=judgment,
        articles=articles,
        cited_articles=cited_articles,
        cited_judgments=cited_judgments,
        same_as=[JudgmentSummaryDTO.from_document(doc) for doc in data.same_as],
        related_to=[RelatedJudgmentDTO.from_document(doc) for doc in data.related_to],
        series=[JudgmentSummaryDTO.from_document(doc) for doc in data.series],
        conclusions=[JudgmentConclusionDTO(**c) for c in data.conclusions],
        metadata=data.metadata or None,
    )


def _citation_spans(
    relations: list[JudgmentArticleRelation], cited: list[dict[str, Any]]
) -> dict[tuple[str, str | None], list[ArticleCitationSpan]]:
    """The stored mentions of every cited article and judgment, as citation spans, by
    ``(paragraph_id, footnote)``: a paragraph's own under ``None``, a footnote's under its
    label (``core.mentions.mention_texts``).

    Detected when the judgment was linked (``semantic rechtspraak``, ``semantic
    rechtspraak-citations``), so serving one costs no detection.
    """
    spans: dict[tuple[str, str | None], list[ArticleCitationSpan]] = {}

    def add(target: ArticleCitationTarget, meta: dict[str, Any], kind: str) -> None:
        for mention in mentions_of(meta):
            spans.setdefault((mention.paragraph_id, mention.footnote), []).append(
                ArticleCitationSpan(
                    start=mention.start,
                    end=mention.end,
                    text=mention.raw_match,
                    target=target,
                    kind=kind,
                    confidence=mention.confidence,
                    **mention.parts.to_dict(),
                )
            )

    for relation in relations:
        add(
            ArticleCitationTarget.from_document(relation.article),
            relation.meta,
            "article",
        )
    for doc in cited:
        add(ArticleCitationTarget.from_document(doc), doc.get("meta") or {}, "judgment")
    for found in spans.values():
        found.sort(key=lambda span: span.start or 0)
    return spans
