"""Annex endpoint: one annex with the articles referring to it."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.annexes import (
    AnnexDetailResponse,
    AnnexDTO,
    AnnexReferencedByItem,
)
from lawgraph.api.schemas.common import ArticleRelationDTO, scope_type_of
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries.annexes import (
    get_annex,
    get_annex_referenced_by,
)
from lawgraph.db.queries.not_found import require

router = APIRouter()
logger = get_logger(__name__)


def _referenced_by_items(rows: list[dict[str, Any]]) -> list[AnnexReferencedByItem]:
    items: list[AnnexReferencedByItem] = []
    for row in rows:
        edge = row.get("edge") or {}
        meta = edge.get("meta") or {}
        items.append(
            AnnexReferencedByItem(
                article=ArticleRelationDTO.from_documents(row["article"], None),
                scope_type=scope_type_of(meta),
                explanation=edge.get("explanation"),
            )
        )
    return items


@router.get(
    "/{key}",
    response_model=AnnexDetailResponse,
    summary="Annex detail",
    description="One annex with its entries and every article referring to it.",
    tags=["annexes"],
)
def get_annex_detail(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> AnnexDetailResponse:
    doc = require(get_annex(store, key), "Annex", key)
    rows = get_annex_referenced_by(store, key)
    return AnnexDetailResponse(
        annex=AnnexDTO.from_document(doc),
        referenced_by=_referenced_by_items(rows),
    )
