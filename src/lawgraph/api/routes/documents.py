"""Document endpoints.

GET /api/documents        — the papers of the chambers, newest first, with facets
GET /api/documents/{key}  — one document with its text, its sections and what it explains
GET /api/documents/{key}/passages — the passages of a memorandum that explain an article
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import parse_choices
from lawgraph.api.schemas.documents import (
    DocumentListItemDTO,
    DocumentListResponse,
    DocumentPassagesResponse,
    DocumentTextResponse,
    PassageDTO,
    readable_sections,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries.committees import load_member_slugs
from lawgraph.db.queries.decisions import get_document_decisions
from lawgraph.db.queries.documents import (
    get_document,
    get_document_links,
    get_document_passages,
    get_replacements,
    list_documents,
)
from lawgraph.db.queries.dossiers import load_dossier_names

router = APIRouter()


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="The papers of the chambers",
    description=(
        "The papers of the Tweede Kamer and the Eerste Kamer, newest first, with their "
        "metadata (no text): ``chamber``, ``kind``, ``dossier_number`` (the dossier it is "
        "numbered in), ``number`` (the nr., or the letter of the Eerste Kamer), ``date``, "
        "``title`` and ``session_year``. ``facets`` counts per ``kind`` and ``chamber``, "
        "each without its own filter; ``facets=false`` reads one page only."
    ),
    tags=["documents"],
)
def list_chamber_documents(
    store: Annotated[GraphStore, Depends(get_store)],
    chamber: Annotated[
        Literal["TK", "EK"] | None, Query(description="One chamber; both by default.")
    ] = None,
    kind: Annotated[
        str | None,
        Query(description="Comma-separated kinds, as the chamber writes them."),
    ] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="A dossier label (``36791``, ``37020-XV``): the papers part of it.",
            pattern=r"^\d+(-[A-Za-z0-9()]+)?$",
        ),
    ] = None,
    date_from: Annotated[
        dt.date | None, Query(alias="from", description="On or after, YYYY-MM-DD.")
    ] = None,
    date_to: Annotated[
        dt.date | None, Query(alias="to", description="On or before, YYYY-MM-DD.")
    ] = None,
    facets: Annotated[bool, Query(description="Count per kind and chamber.")] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    raw = list_documents(
        store,
        chambers=(chamber,) if chamber else ("TK", "EK"),
        kinds=parse_choices(kind, None, "kind"),
        dossier=dossier,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        limit=limit,
        offset=offset,
        facets=facets,
    )
    names = load_dossier_names(store)
    return DocumentListResponse(
        total=raw.get("total"),
        items=[
            DocumentListItemDTO.from_row(row, names) for row in raw.get("items") or []
        ],
        facets=raw.get("facets"),
    )


@router.get(
    "/{key}",
    response_model=DocumentTextResponse,
    summary="Document text",
    description=(
        "One document with its text, read from the XML of the paper, its "
        "`sections` (the headings of the paper with their offsets into `text`), "
        "the dossiers it belongs to and, for an explanatory document, the "
        "articles and laws it explains, and the votes taken on it (`decisions`, with the "
        "vote of every faction). "
        "`text` is null when `normalize tk-content` has not reached it."
    ),
    tags=["documents"],
)
def get_document_text(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DocumentTextResponse:
    doc = get_document(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document '{key}' not found.")
    return DocumentTextResponse.from_document(
        doc,
        get_document_links(store, doc["_id"]),
        get_document_decisions(store, doc["_id"]),
        load_dossier_names(store),
        load_member_slugs(store),
        get_replacements(store, [doc["_id"]]).get(doc["_id"]),
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
    store: Annotated[GraphStore, Depends(get_store)],
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
            changed=row.get("changed"),
            explanation=row.get("explanation"),
        )
        for row in rows
    ]
    return DocumentPassagesResponse(total=len(items), items=items)
