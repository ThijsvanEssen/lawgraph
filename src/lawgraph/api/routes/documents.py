"""Document endpoints.

GET /api/documents        — the papers of the chambers, newest first, with facets
GET /api/documents/{key}  — one document with its text, its sections and what it explains
GET /api/documents/{key}/passages — the passages of a memorandum that explain an article
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import (
    DOSSIER_NUMBER_PATTERN,
    After,
    PageLimit,
    not_both,
    parse_choices,
)
from lawgraph.api.schemas.documents import (
    DocumentListItemDTO,
    DocumentListResponse,
    DocumentPassagesResponse,
    DocumentTextResponse,
    PassageDTO,
    readable_sections,
)
from lawgraph.config.constants import Chamber
from lawgraph.core.letter_kinds import LetterKind
from lawgraph.core.motion_kinds import MOTION_KINDS
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import get_document_decisions
from lawgraph.db.queries.documents import (
    document_xml_retrieval,
    get_document,
    get_document_links,
    get_document_passages,
    get_replacements,
    list_documents,
)
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.not_found import require
from lawgraph.db.queries.unlinked_references import reference_counts

router = APIRouter()

# The deepest page of the list: a page reads every paper before it, newest first (prod, 22
# Oct: 22 s at offset 50,000, past the read ceiling at 300,000). Deeper, a window of dates.
OFFSET_MAX = 10_000


@router.get(
    "",
    response_model=DocumentListResponse,
    summary="The papers of the chambers",
    description=(
        "The papers of the Tweede Kamer and the Eerste Kamer, newest first, with their "
        "metadata (no text): ``chamber``, ``kind``, ``dossier_number`` (the dossier it is "
        "numbered in), ``number`` (the nr., or the letter of the Eerste Kamer), ``date``, "
        "``title`` and ``session_year``; of a motion or an amendment how it ended "
        "(``outcome``) and of a motion of censure or of no confidence ``motion_kind``. "
        "``motion_kind=censure,no_confidence`` keeps those motions: one open while its "
        "``outcome`` is null. ``letter_kind=article_100`` keeps the artikel 100-brieven of "
        "the government, as their subject names them. ``facets`` counts per ``kind`` and "
        "``chamber``, each without its own filter; ``facets=false`` reads one page only."
    ),
    tags=["documents"],
)
def list_chamber_documents(
    store: Annotated[GraphStore, Depends(get_store)],
    chamber: Annotated[
        Chamber | None, Query(description="One chamber; both by default.")
    ] = None,
    kind: Annotated[
        str | None,
        Query(description="Comma-separated kinds, as the chamber writes them."),
    ] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="A dossier label (``36791``, ``37020-XV``): the papers part of it.",
            pattern=DOSSIER_NUMBER_PATTERN,
        ),
    ] = None,
    date_from: Annotated[
        dt.date | None, Query(alias="from", description="On or after, YYYY-MM-DD.")
    ] = None,
    date_to: Annotated[
        dt.date | None, Query(alias="to", description="On or before, YYYY-MM-DD.")
    ] = None,
    motion_kind: Annotated[
        str | None,
        Query(
            description="Comma-separated kinds of motion: ``censure`` (motie van "
            "afkeuring), ``no_confidence`` (motie van wantrouwen). Only those motions."
        ),
    ] = None,
    letter_kind: Annotated[
        LetterKind | None,
        Query(
            description="A kind of letter of the government that its subject names: "
            "``article_100`` the artikel 100-brieven (a deployment of the armed forces, "
            "artikel 100 Grondwet). Only those letters."
        ),
    ] = None,
    facets: Annotated[bool, Query(description="Count per kind and chamber.")] = True,
    limit: PageLimit = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            le=OFFSET_MAX,
            description=f"Papers to skip, at most {OFFSET_MAX:,}: further back, `to` the "
            "date of the last paper of a page (and `offset` the papers of that date it "
            "showed).",
        ),
    ] = 0,
    after: After = None,
) -> DocumentListResponse:
    not_both(after, offset)
    raw = list_documents(
        store,
        chambers=(chamber,) if chamber else ("TK", "EK"),
        kinds=parse_choices(kind, None, "kind"),
        dossier=dossier,
        from_date=iso_day(date_from),
        to_date=iso_day(date_to),
        motion_kinds=parse_choices(motion_kind, MOTION_KINDS, "motion_kind"),
        letter_kind=letter_kind,
        limit=limit,
        offset=offset,
        after=after,
        facets=facets,
    )
    names = load_dossier_names(store)
    return DocumentListResponse(
        next_cursor=raw.get("next_cursor"),
        total=raw.get("total"),
        partial=bool(raw.get("partial")),
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
        "its `paragraphs` (each line of `text` with a lasting id and its alinea number), "
        "its `tables` (each a span of `text`, a row a line and its cells separated by a "
        "tab), "
        "the dossiers it belongs to and, for an explanatory document, the "
        "articles and laws it explains, and the votes taken on it (`decisions`, with the "
        "vote of every faction). "
        "`text` is null when `normalize tk-content` has not reached it; "
        "`completeness.text` says why (pending, not in the source, not fetched, or read and "
        "empty)."
    ),
    tags=["documents"],
)
def get_document_text(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DocumentTextResponse:
    doc = require(get_document(store, key), "Document", key)
    return DocumentTextResponse.from_document(
        doc,
        get_document_links(store, doc["id"]),
        get_document_decisions(store, doc["id"]),
        load_dossier_names(store),
        get_replacements(store, [doc["id"]]).get(doc["id"]),
        reference_counts(store, doc["id"]),
        document_xml_retrieval(store, doc),
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
    doc = require(get_document(store, key), "Document", key)
    props = doc.get("props") or {}
    text: str | None = props.get("text")
    if not text:
        return DocumentPassagesResponse(total=0, items=[])
    levels = {s.id: s.level for s in readable_sections(text, props.get("sections"))}
    rows = [
        row
        for row in get_document_passages(store, doc["id"], bwb_id, article)
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
