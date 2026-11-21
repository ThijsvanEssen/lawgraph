from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import NOT_FOUND
from lawgraph.api.schemas.concepts import ConceptResponse
from lawgraph.core.concept_articles import concepts
from lawgraph.db import GraphStore
from lawgraph.db.queries.concepts import concept_overview
from lawgraph.db.queries.not_found import NotFound

router = APIRouter()


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
    key: Annotated[str, Path(description="`toetsing-van-wetten`.")],
    store: Annotated[GraphStore, Depends(get_store)],
) -> ConceptResponse:
    concept = concepts().get(key)
    if concept is None:
        raise NotFound("Concept", key)
    return ConceptResponse.of(concept, concept_overview(store, concept.article_ids))
