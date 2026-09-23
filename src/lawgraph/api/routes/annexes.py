"""Annex endpoints — detail, referenced-by, and cross-law listing."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.annexes import (
    AnnexDetailResponse,
    AnnexDTO,
    AnnexListItem,
    AnnexListResponse,
    AnnexReferencedByItem,
)
from lawgraph.api.schemas.common import ArticleRelationDTO
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore
from lawgraph.db.queries.annexes import (
    get_annex,
    get_annex_referenced_by,
    list_annexes,
)

router = APIRouter()
logger = get_logger(__name__)


def _referenced_by_items(rows: list[dict]) -> list[AnnexReferencedByItem]:
    items: list[AnnexReferencedByItem] = []
    for row in rows:
        edge = row.get("edge") or {}
        meta = edge.get("meta") or {}
        items.append(
            AnnexReferencedByItem(
                article=ArticleRelationDTO.from_documents(row["article"], None),
                scope_type=meta.get("scope_type") or "fixed",
                explanation=edge.get("explanation"),
            )
        )
    return items


@router.get(
    "",
    response_model=AnnexListResponse,
    summary="List annexes",
    description=(
        "Annexes, optionally filtered to one law (bwb_id) or limited to the "
        "annexes used by articles of more than one law (shared_across_laws=true)."
    ),
    tags=["annexes"],
)
def get_annexes(
    store: Annotated[ArangoStore, Depends(get_store)],
    bwb_id: Annotated[str | None, Query()] = None,
    shared_across_laws: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AnnexListResponse:
    rows, total = list_annexes(
        store,
        bwb_id=bwb_id,
        shared_across_laws=shared_across_laws,
        limit=limit,
        offset=offset,
    )
    items = [
        AnnexListItem(
            annex=AnnexDTO.from_document(row["annex"]),
            referencing_laws=list(row.get("referencing_laws") or []),
        )
        for row in rows
    ]
    return AnnexListResponse(annexes=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{key}",
    response_model=AnnexDetailResponse,
    summary="Annex detail",
    description="One annex with its entries and every article referring to it.",
    tags=["annexes"],
)
def get_annex_detail(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> AnnexDetailResponse:
    doc = get_annex(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail="Annex not found")
    rows = get_annex_referenced_by(store, key)
    return AnnexDetailResponse(
        annex=AnnexDTO.from_document(doc),
        referenced_by=_referenced_by_items(rows),
    )


@router.get(
    "/{key}/referenced-by",
    response_model=list[AnnexReferencedByItem],
    summary="Articles referring to this annex",
    description="Every article, across all laws, that uses this annex as its scope.",
    tags=["annexes"],
)
def get_referenced_by(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[AnnexReferencedByItem]:
    if get_annex(store, key) is None:
        raise HTTPException(status_code=404, detail="Annex not found")
    return _referenced_by_items(get_annex_referenced_by(store, key))
