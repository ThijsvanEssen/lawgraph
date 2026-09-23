"""Document endpoints.

GET /api/documents        — the document index
GET /api/documents/{key}  — one document with its text, its sections and what it explains
GET /api/documents/{key}/passages — the passages of a memorandum that explain an article
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.documents import (
    DocumentListResponse,
    DocumentPassagesResponse,
    DocumentSummaryDTO,
    DocumentTextResponse,
    PassageDTO,
    readable_sections,
)
from lawgraph.api.schemas.dossiers import DOSSIER_NUMBER_PATTERN
from lawgraph.db import ArangoStore
from lawgraph.db.queries.documents import (
    get_document,
    get_document_links,
    get_document_passages,
)
from lawgraph.db.queries.documents import list_documents as query_documents
from lawgraph.db.queries.dossiers import get_dossier_by_number

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
        "One document with its text, read from the XML of the paper, its "
        "`sections` (the headings of the paper with their offsets into `text`), "
        "the dossiers it belongs to and, for an explanatory document, the "
        "articles and laws it explains. "
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
    return DocumentTextResponse.from_document(
        doc, get_document_links(store, doc["_id"])
    )


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
