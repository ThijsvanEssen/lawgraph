"""Document endpoints.

GET /api/documents        — the document index
GET /api/documents/{key}  — one document with its text and sections
GET /api/documents/{key}/passages — the passages of a memorandum that explain an article
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.documents import get_document, get_document_passages
from lawgraph.api.queries.documents import list_documents as query_documents
from lawgraph.api.schemas.documents import (
    DocumentListResponse,
    DocumentPassagesResponse,
    DocumentSummaryDTO,
    DocumentTextResponse,
    PassageDTO,
    readable_sections,
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
    chamber: Annotated[str | None, Query(description="'TK' or 'EK'.")] = None,
    source: Annotated[
        str | None,
        Query(description="Source, e.g. 'tk', 'eerstekamer', 'staatscourant'."),
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
        "One document with its text, read from the XML of the paper, and its "
        "`sections`: the headings of the paper with their offsets into `text`. "
        "`text` is null when `normalize tk-content` has not reached it."
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


@router.get(
    "/{key}/passages",
    response_model=DocumentPassagesResponse,
    summary="Passages of a memorandum that explain an article",
    description=(
        "The sections of a memorandum (MvT, NvT) that `semantic tk-mvt-articles` linked to "
        "the article (or to one of its versions) with `EXPLAINS`, in document order: each "
        "with its `text` (a slice of the document text), `confidence` and `match_type`. "
        "Empty when the document has no text or no section explains the article; 404 when "
        "the document is unknown."
    ),
    tags=["documents"],
)
def get_document_article_passages(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    bwb_id: Annotated[
        str, Query(min_length=1, max_length=64, description="BWB id of the law.")
    ],
    article: Annotated[
        str,
        Query(
            min_length=1, max_length=64, description="Article number, e.g. `5`, `1a`."
        ),
    ],
) -> DocumentPassagesResponse:
    doc = get_document(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document '{key}' not found.")
    props = doc.get("props") or {}
    text: str | None = props.get("text")
    if not text:
        return DocumentPassagesResponse(total=0, items=[])
    levels = {s.id: s.level for s in readable_sections(text, props.get("sections"))}
    rows = [
        row
        for row in get_document_passages(store, doc["_id"], bwb_id, article)
        if row["char_end"] <= len(text)
    ]
    rows.sort(key=lambda row: (row["char_start"], row["section_anchor"]))
    items = [
        PassageDTO(
            section_id=row["section_anchor"],
            heading=row["heading"],
            level=levels.get(row["section_anchor"]),
            char_start=row["char_start"],
            char_end=row["char_end"],
            text=text[row["char_start"] : row["char_end"]],
            confidence=row["confidence"],
            match_type=row["match_type"],
        )
        for row in rows
    ]
    return DocumentPassagesResponse(total=len(items), items=items)
