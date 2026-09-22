"""Document endpoints.

GET /api/documents        — the document index
GET /api/documents/{key}  — one document with its text and what it explains
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.documents import get_document, get_document_links
from lawgraph.api.queries.documents import list_documents as query_documents
from lawgraph.api.queries.dossiers import get_dossier_by_number
from lawgraph.api.schemas.documents import (
    DocumentListResponse,
    DocumentSummaryDTO,
    DocumentTextResponse,
)
from lawgraph.api.schemas.dossiers import DOSSIER_NUMBER_PATTERN
from lawgraph.db import ArangoStore

router = APIRouter()


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="Document index",
    description=(
        "Documents across every source, with metadata only — no text. Backs "
        "the document index page. ``total`` is the absolute number of matches, "
        "independent of ``limit`` and ``offset``. ``dossier`` keeps the documents "
        "of one dossier, linked directly or through a case; an unknown dossier "
        "matches nothing."
    ),
    tags=["documents"],
)
def list_documents(
    store: Annotated[ArangoStore, Depends(get_store)],
    q: Annotated[str | None, Query(description="Filter on title and kind.")] = None,
    kind: Annotated[
        str | None, Query(description="Document kind, exact match.")
    ] = None,
    chamber: Annotated[str | None, Query(description="'TK' or 'EK'.")] = None,
    source: Annotated[
        str | None,
        Query(description="Source, e.g. 'tk', 'eerstekamer', 'staatscourant'."),
    ] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="Dossier number, e.g. 29684.",
            pattern=DOSSIER_NUMBER_PATTERN,
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    dossier_id = None
    if dossier:
        found = get_dossier_by_number(store, dossier)
        if found is None:
            return DocumentListResponse(total=0, items=[])
        dossier_id = found["_id"]
    raw = query_documents(
        store,
        q=q,
        kind=kind,
        chamber=chamber,
        source=source,
        dossier_id=dossier_id,
        limit=limit,
        offset=offset,
    )
    return DocumentListResponse(
        total=int(raw.get("total") or 0),
        items=[DocumentSummaryDTO.from_row(row) for row in raw.get("items") or []],
    )


@router.get(
    "/{key}",
    response_model=DocumentTextResponse,
    summary="Document text",
    description=(
        "One document with its text, read from the XML of the paper, the dossiers "
        "it belongs to and, for an explanatory document, the articles and laws it "
        "explains. "
        "``text`` is null when ``normalize tk-content`` has not reached it."
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
    return DocumentTextResponse.from_document(
        doc, get_document_links(store, doc["_id"])
    )
