"""Instrument list endpoint — paginated catalogue of laws and regulations."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.common import JudgmentSummaryDTO
from lawgraph.api.schemas.instruments import (
    TEXT_PREVIEW_CHARS,
    AmendedByResponse,
    AmendingInstrumentDTO,
    CitedArticleRef,
    EuLinkDTO,
    InstrumentArticleNodeDTO,
    InstrumentArticlesAtResponse,
    InstrumentArticlesResponse,
    InstrumentArticleVersionDTO,
    InstrumentDetailDTO,
    InstrumentDossierItem,
    InstrumentDossiersResponse,
    InstrumentEuLinksResponse,
    InstrumentJudgmentItem,
    InstrumentJudgmentsResponse,
    InstrumentListItemDTO,
    InstrumentListResponse,
    InstrumentRelatedItem,
    InstrumentRelatedResponse,
    InstrumentVersionDTO,
    InstrumentVersionsResponse,
    InternationalLinkDTO,
    LinkedInstrumentDTO,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries._helpers import props as _props
from lawgraph.db.queries.instrument_links import (
    get_eu_links,
    get_international_links,
)
from lawgraph.db.queries.instrument_scope import (
    resolve_instrument,
    same_treaty,
    scope_of_node,
)
from lawgraph.db.queries.instruments import (
    INSTRUMENT_SORTS,
    get_articles,
    get_articles_at,
    get_instrument_amended_by,
    get_instrument_dossiers,
    get_instrument_judgments,
    get_instrument_related_instruments,
    get_instrument_versions,
    get_instruments_list,
)


def _extract_judgment_item(row: dict) -> InstrumentJudgmentItem:
    judgment = row.get("judgment") or {}
    props = _props(judgment)
    return InstrumentJudgmentItem(
        id=judgment.get("_id") or "",
        key=judgment.get("_key") or "",
        ecli=props.get("ecli"),
        display_name=props.get("display_name"),
        cited_articles=[
            CitedArticleRef(**a) for a in (row.get("cited_articles") or [])
        ],
    )


router = APIRouter()


@router.get(
    "",
    response_model=InstrumentListResponse,
    summary="Paginated list of instruments",
    description=(
        "A paginated list of statutes, regulations and EU instruments. Supports "
        "free-text search (`q`), a jurisdiction filter (`nl`/`eu`), a kind "
        "filter and a minimum article count."
    ),
    tags=["instruments"],
)
def list_instruments(
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(description="Free-text match")] = None,
    jurisdiction: Annotated[Literal["nl", "eu"] | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    article_count_min: Annotated[int | None, Query(ge=0)] = None,
    sort: Annotated[Literal["title", "article_count"], Query()] = "title",
) -> InstrumentListResponse:
    if sort not in INSTRUMENT_SORTS:  # belt-and-braces; Literal already validates
        sort = "title"
    data = get_instruments_list(
        store,
        q=q,
        jurisdiction=jurisdiction,
        kind=kind,
        article_count_min=article_count_min,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    items = [InstrumentListItemDTO.from_document(row) for row in data.get("items", [])]
    return InstrumentListResponse(items=items, total=int(data.get("total", 0)))


def _instrument_or_404(store: ArangoStore, identifier: str) -> dict:
    doc = resolve_instrument(store, identifier)
    if doc is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return doc


@router.get(
    "/{identifier}",
    response_model=InstrumentDetailDTO,
    summary="One instrument",
    description=(
        "The instrument named by its BWB id (`BWBR0001854`), its CELEX number "
        "(`32016L0680`) or its node key (`echr_convention`, `verdrag_012345`): "
        "identifiers, names, jurisdiction, kind, dates and article count, and for a "
        "treaty the other instruments with its treaty number (`same_treaty`). 404 for "
        "an unknown instrument."
    ),
    tags=["instruments"],
)
def get_instrument(
    identifier: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentDetailDTO:
    doc = _instrument_or_404(store, identifier)
    return InstrumentDetailDTO.from_document(doc, same_treaty=same_treaty(store, doc))


def _international_link(
    row: dict, kind: Literal["treaty", "echr_judgment"]
) -> InternationalLinkDTO:
    """One `international` item from a treaty row or an ECHR judgment row."""
    edge = row.get("edge") or {}
    own = row.get("own_article")
    counterpart = row.get("counterpart_article")
    return InternationalLinkDTO(
        kind=kind,
        instrument=(
            LinkedInstrumentDTO.from_document(row["instrument"])
            if kind == "treaty"
            else None
        ),
        judgment=(
            JudgmentSummaryDTO.from_document(row["judgment"])
            if kind == "echr_judgment"
            else None
        ),
        own_article=CitedArticleRef(**own) if own else None,
        counterpart_article=CitedArticleRef(**counterpart) if counterpart else None,
        confidence=edge.get("confidence"),
        source=edge.get("source"),
        meta=edge.get("meta") or {},
    )


@router.get(
    "/{identifier}/eu-links",
    response_model=InstrumentEuLinksResponse,
    summary="EU and international links of an instrument",
    description=(
        "`implements`: EU acts whose CELEX number the text of this instrument names. "
        "`implemented_by`: national regulations that name the CELEX number of this EU "
        "act. Both are `IMPLEMENTS` edges between instruments, written from a CELEX "
        "number named in the text (`basis`): not a transposition relation, not per "
        "article. `international`: treaties (BWB treaties) that articles of this "
        "instrument refer to, and ECHR judgments that refer to it or to its articles, "
        "each with the evidence of its edge; the graph holds no other links to treaties "
        "or to the articles of the ECHR Convention from Dutch text. The instrument is "
        "named by BWB id, CELEX number or node key; 404 when unknown. `limit` bounds "
        "each list; the `*_total` fields are absolute."
    ),
    tags=["instruments"],
)
def get_instrument_eu_links(
    identifier: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentEuLinksResponse:
    doc = _instrument_or_404(store, identifier)
    eu = get_eu_links(store, doc["_id"], limit=limit)
    international = get_international_links(
        store, doc["_id"], scope_of_node(doc), limit=limit
    )
    links = [_international_link(r, "treaty") for r in international.treaties] + [
        _international_link(r, "echr_judgment") for r in international.judgments
    ]
    return InstrumentEuLinksResponse(
        instrument=LinkedInstrumentDTO.from_document(doc),
        implements=[EuLinkDTO.from_row(r) for r in eu.implements],
        implements_total=eu.implements_total,
        implemented_by=[EuLinkDTO.from_row(r) for r in eu.implemented_by],
        implemented_by_total=eu.implemented_by_total,
        international=links[:limit],
        international_total=international.treaties_total
        + international.judgments_total,
    )


@router.get(
    "/{bwb_id}/articles",
    response_model=InstrumentArticlesResponse,
    summary="All articles of an instrument",
    description=(
        "The articles in force of this instrument (BWB id or CELEX number), in the order "
        "of the document: an article with only a heading (the Algemene bepaling of the "
        "Grondwet) where it stands, an annex after the regulation. `include_repealed` "
        "adds the repealed identities (last). The text is a short preview; "
        "/api/articles/{bwb_id}/{address} has the full content."
    ),
    tags=["instruments"],
)
def list_articles(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    include_stubs: Annotated[
        bool,
        Query(description="Include placeholder/stub articles (default: false)"),
    ] = False,
    include_repealed: Annotated[
        bool,
        Query(
            description="Include the articles no longer in force: identities whose "
            "number another article has now, and articles their current version repeals."
        ),
    ] = False,
    text_preview_chars: Annotated[
        int, Query(ge=0, le=600, description="Chars of text to inline as preview")
    ] = 160,
    limit: Annotated[int, Query(ge=1, le=2000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InstrumentArticlesResponse:
    docs, total = get_articles(
        store,
        bwb_id,
        include_stubs=include_stubs,
        include_repealed=include_repealed,
        limit=limit,
        offset=offset,
    )
    return InstrumentArticlesResponse(
        bwb_id=bwb_id,
        total=total,
        items=[
            InstrumentArticleNodeDTO.from_document(
                d, text_preview_chars=text_preview_chars
            )
            for d in docs
        ],
    )


@router.get(
    "/{bwb_id}/judgments",
    response_model=InstrumentJudgmentsResponse,
    summary="Every judgment citing this instrument",
    description=(
        "Per judgment: light metadata plus the specific articles it refers to. "
        "Meant for the case-law layer of the graph. ``total`` is the absolute "
        "count, independent of ``limit``."
    ),
    tags=["instruments"],
)
def get_instrument_judgments_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentJudgmentsResponse:
    rows, total = get_instrument_judgments(store, bwb_id, limit=limit)
    items = [_extract_judgment_item(row) for row in rows]
    return InstrumentJudgmentsResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/dossiers",
    response_model=InstrumentDossiersResponse,
    summary="Parliamentary dossiers touching this law",
    description=(
        "Dossiers reached through LEGISLATED_IN from (a) the regulation itself "
        "and (b) the amending publications (Stb/Trb) that change, introduce or "
        "repeal one of its articles. ``via`` says how the dossier is linked "
        "(``instrument`` or ``amending_publication``; in the latter case "
        "``publication`` names the newest publication). ``total`` is the "
        "absolute count, independent of ``limit``."
    ),
    tags=["instruments"],
)
def get_instrument_dossiers_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> InstrumentDossiersResponse:
    rows, total = get_instrument_dossiers(store, bwb_id, limit=limit)
    items = []
    for row in rows:
        d = row["dossier"]
        items.append(
            InstrumentDossierItem(
                id=d.get("_id") or "",
                key=d.get("_key") or "",
                dossier_number=_props(d)["label"],
                title=_props(d).get("title"),
                display_name=_props(d).get("display_name"),
                current_phase=_props(d).get("current_phase"),
                opened_on=_props(d).get("opened_on"),
                closed=_props(d).get("closed"),
                via=row["via"],
                publication=row.get("publication"),
            )
        )
    return InstrumentDossiersResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/amended-by",
    response_model=AmendedByResponse,
    summary="Amending publications of a regulation",
    description=(
        "The amending instruments (Staatsblad, Tractatenblad, ...) that change, "
        "introduce or repeal articles of this regulation (AMENDS / INTRODUCES / "
        "REPEALS), newest first. Per publication: the edge count per kind, the "
        "number of articles affected, the first effective date and the "
        "dossiers. ``total`` is the absolute count, independent of ``limit`` "
        "and ``offset``."
    ),
    tags=["instruments"],
)
def get_instrument_amended_by_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AmendedByResponse:
    data = get_instrument_amended_by(store, bwb_id, limit=limit, offset=offset)
    items = [AmendingInstrumentDTO.from_row(r, data.dossier_titles) for r in data.items]
    return AmendedByResponse(bwb_id=bwb_id, total=data.total, items=items)


@router.get(
    "/{bwb_id}/related-instruments",
    response_model=InstrumentRelatedResponse,
    summary="Instruments referring to this one, or referred to by it",
    description=(
        "An aggregation of the REFERS_TO edges between articles of this law and "
        "articles of other laws. Each related instrument carries "
        "`outbound_count` (references from this law to the other) and "
        "`inbound_count` (references from the other law to this one). "
        "``total`` is the absolute count, independent of ``limit``."
    ),
    tags=["instruments"],
)
def get_instrument_related_route(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> InstrumentRelatedResponse:
    rows, total = get_instrument_related_instruments(store, bwb_id, limit=limit)
    items = [
        InstrumentRelatedItem(
            id=(r.get("instrument") or {}).get("_id") or "",
            key=(r.get("instrument") or {}).get("_key") or "",
            bwb_id=((r.get("instrument") or {}).get("props") or {}).get("bwb_id"),
            celex=((r.get("instrument") or {}).get("props") or {}).get("celex"),
            display_name=((r.get("instrument") or {}).get("props") or {}).get(
                "display_name"
            ),
            citation_title=((r.get("instrument") or {}).get("props") or {}).get(
                "citation_title"
            ),
            outbound_count=int(r.get("outbound_count") or 0),
            inbound_count=int(r.get("inbound_count") or 0),
        )
        for r in rows
    ]
    return InstrumentRelatedResponse(bwb_id=bwb_id, total=total, items=items)


@router.get(
    "/{bwb_id}/versions",
    response_model=InstrumentVersionsResponse,
    summary="Historical versions of an instrument",
    description=(
        "Every historical toestand (version) of a BWB law, newest first. Each "
        "version carries a validity period (valid_from, valid_until); the "
        "current one has ``current=true``."
    ),
    tags=["instruments"],
)
def list_instrument_versions(
    bwb_id: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> InstrumentVersionsResponse:
    docs = get_instrument_versions(store, bwb_id)
    items = [InstrumentVersionDTO.from_document(d) for d in docs]
    return InstrumentVersionsResponse(bwb_id=bwb_id, total=len(items), items=items)


@router.get(
    "/{bwb_id}/articles/at/{at_date}",
    response_model=InstrumentArticlesAtResponse,
    summary="Articles as they stood on a given date",
    description=(
        "The articles of a BWB instrument as they applied on ``at_date`` "
        "(YYYY-MM-DD), read from the article versions, in the order of that day's "
        "toestand, each with the divisions it stood in that day (``breadcrumb``). Empty "
        "before the first toestand of the law (``first_version_from``) and when no "
        "version covers that date. ``text_preview`` is the start of the text; with "
        "``text_preview_chars`` the whole ``text`` is left out unless "
        "``include_text=true``. ``limit`` and ``offset`` page, ``total`` counts every "
        "article."
    ),
    tags=["instruments"],
)
def list_articles_at(
    bwb_id: str,
    at_date: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    text_preview_chars: Annotated[
        int | None,
        Query(
            ge=0,
            le=600,
            description=f"Chars of text to inline as preview (default "
            f"{TEXT_PREVIEW_CHARS}); given, the "
            "whole text is left out unless include_text=true",
        ),
    ] = None,
    include_text: Annotated[
        bool | None,
        Query(
            description="Give the whole text; default: true unless text_preview_chars "
            "is given"
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InstrumentArticlesAtResponse:
    try:
        dt.date.fromisoformat(at_date)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="at_date must be YYYY-MM-DD"
        ) from None
    law = get_articles_at(store, bwb_id, at_date, limit=limit, offset=offset)
    whole = text_preview_chars is None if include_text is None else include_text
    return InstrumentArticlesAtResponse(
        bwb_id=bwb_id,
        at_date=at_date,
        total=law.total,
        first_version_from=law.first_version_from,
        items=[
            InstrumentArticleVersionDTO.from_document(
                d,
                on=at_date,
                text_preview_chars=(
                    TEXT_PREVIEW_CHARS
                    if text_preview_chars is None
                    else text_preview_chars
                ),
                include_text=whole,
            )
            for d in law.items
        ],
    )
