from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import NOT_FOUND
from lawgraph.api.params import (
    CitedBySort,
    CourtCode,
    JudgmentYear,
    ListLimit,
    PageLimit,
    SubjectArea,
    Tiers,
    area_value,
    tier_values,
)
from lawgraph.api.schemas.article_cited_by import CitedByFacets
from lawgraph.api.schemas.concepts import (
    ConceptDocumentsResponse,
    ConceptJudgmentsResponse,
    ConceptResponse,
    document_items,
    judgment_items,
)
from lawgraph.core.concept_articles import Concept, concepts
from lawgraph.db import GraphStore
from lawgraph.db.queries.concepts import (
    concept_documents,
    concept_judgments,
    concept_overview,
)
from lawgraph.db.queries.not_found import NotFound

router = APIRouter()

ConceptKey = Annotated[str, Path(description="`toetsing-van-wetten`.")]


def _concept(key: str) -> Concept:
    concept = concepts().get(key)
    if concept is None:
        raise NotFound("Concept", key)
    return concept


@router.get(
    "/{key}",
    response_model=ConceptResponse,
    summary="A concept: articles that make one doctrine, and what cites them",
    description=(
        "A concept kept by hand (`concepts` of an article names its keys): its articles "
        "in the order of the list, each with its heading or the start of its text and "
        "the judgments that cite it; the judgments that cite any of them, each once "
        "(`judgment_total`), and the newest five; the papers an edge joins to any of "
        "them (a memorandum that explains it, a paper that names it), each once "
        "(`document_total`), and the newest two; and a link to an official page that "
        "explains it. `missing` names an article of the list the data does not hold. "
        "404 when no concept has the key."
    ),
    responses=NOT_FOUND,
    tags=["concepts"],
)
def get_concept(
    key: ConceptKey,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ConceptResponse:
    concept = _concept(key)
    return ConceptResponse.of(concept, concept_overview(store, concept.article_ids))


@router.get(
    "/{key}/judgments",
    response_model=ConceptJudgmentsResponse,
    summary="The judgments that cite an article of a concept",
    description=(
        "The judgments that cite any article of the concept, each once with the articles "
        "of the concept it cites (`article_ids`), as the block of `/api/concepts/{key}` "
        "lists its newest five. Filters and `sort` as the passages of an article "
        "(`/api/articles/{bwb_id}/{article_number}/cited-by`): `court` (ECLI court code), "
        "`tier` (repeated: any of them), `year` (of the judgment's date) and "
        "`subject_area` (a main area of law of the judgment's source: `Strafrecht`); "
        "`total` counts the judgments that match, whatever the page (without filters the "
        "`judgment_total` of the block). `facets` counts them per `year` (oldest first, "
        "null for none first), per `tier` and per `subject_area` (most first), each "
        "without its own filter, under the others. `sort`: `date_desc` (default) the "
        "newest first, `citation_count` the most cited first (a standard judgment), then "
        "the newest. 404 when no concept has the key."
    ),
    responses=NOT_FOUND,
    tags=["concepts"],
)
def get_concept_judgments(
    key: ConceptKey,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: PageLimit = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[
        CitedBySort,
        Query(
            description="`date_desc`: the newest judgment first; `citation_count`: the "
            "most cited judgment first (a standard judgment), then the newest."
        ),
    ] = "date_desc",
    court: CourtCode = None,
    tier: Tiers = None,
    year: JudgmentYear = None,
    subject_area: SubjectArea = None,
) -> ConceptJudgmentsResponse:
    concept = _concept(key)
    page = concept_judgments(
        store,
        concept.article_ids,
        limit=limit,
        offset=offset,
        sort=sort,
        court=court,
        tiers=tier_values(tier),
        year=year,
        area=area_value(subject_area),
    )
    return ConceptJudgmentsResponse(
        key=key,
        total=page["total"],
        facets=CitedByFacets.of(page["facets"]),
        items=judgment_items(page["items"]),
    )


@router.get(
    "/{key}/documents",
    response_model=ConceptDocumentsResponse,
    summary="The papers joined to an article of a concept",
    description=(
        "The papers an edge joins to any article of the concept (a memorandum that "
        "explains it, a paper that names it), each once with the articles of the concept "
        "it is joined to (`article_ids`), newest first, as the block of "
        "`/api/concepts/{key}` lists its newest two. `year` (of the paper's date) "
        "filters; `total` counts the papers that match, whatever the page (without "
        "`year` the `document_total` of the block). 404 when no concept has the key."
    ),
    responses=NOT_FOUND,
    tags=["concepts"],
)
def get_concept_documents(
    key: ConceptKey,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: ListLimit = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    year: Annotated[
        str | None,
        Query(
            pattern=r"^\d{4}$", description="The papers of this year (of their date)."
        ),
    ] = None,
) -> ConceptDocumentsResponse:
    concept = _concept(key)
    page = concept_documents(
        store, concept.article_ids, limit=limit, offset=offset, year=year
    )
    return ConceptDocumentsResponse(
        key=key, total=page["total"], items=document_items(page["items"])
    )
