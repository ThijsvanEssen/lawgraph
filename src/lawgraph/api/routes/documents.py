"""Document endpoints.

GET /api/documents        — the document index
GET /api/documents/{key}  — one document with its text
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.documents import get_document
from lawgraph.api.queries.documents import list_documents as query_documents
from lawgraph.api.schemas.documents import (
    DocumentListResponse,
    DocumentSummaryDTO,
    DocumentTextResponse,
)
from lawgraph.core.time import strip_time_component
from lawgraph.db import ArangoStore

router = APIRouter()


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="Document index",
    description=(
        "Documents across every source, with metadata only — no text. Backs "
        "the document index page."
    ),
    tags=["documents"],
)
def list_documents(
    store: Annotated[ArangoStore, Depends(get_store)],
    q: Annotated[str | None, Query(description="Filter on title and kind.")] = None,
    kind: Annotated[
        str | None, Query(description="Document kind, exact match.")
    ] = None,
    chamber: Annotated[
        str | None, Query(description="'TK' (the only chamber loaded).")
    ] = None,
    source: Annotated[
        str | None, Query(description="Source, e.g. 'tk', 'staatscourant'.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> DocumentListResponse:
    rows = query_documents(
        store, q=q, kind=kind, chamber=chamber, source=source, limit=limit
    )
    items = [
        DocumentSummaryDTO(
            key=row["key"],
            title=row.get("title") or None,
            kind=row.get("kind") or None,
            date=strip_time_component(row.get("date")),
            external_id=row.get("external_id") or None,
            source=row.get("source") or None,
            has_text=bool(row.get("has_text")),
            linked_articles=int(row.get("linked_articles") or 0),
        )
        for row in rows
    ]
    return DocumentListResponse(total=len(items), items=items)


@router.get(
    "/{key}",
    response_model=DocumentTextResponse,
    summary="Document text",
    description=(
        "One document with the plain text extracted from its source PDF. "
        "``text`` is null when the hydration pipeline has not reached it."
    ),
    tags=["documents"],
)
def get_document_text(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DocumentTextResponse:
    doc = get_document(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document '{key}' not found.")
    return DocumentTextResponse.from_document(doc)
