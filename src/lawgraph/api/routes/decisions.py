"""Decision (vote) endpoints.

GET /api/decisions            — the vote browser
GET /api/decisions/{key}      — one decision with every vote cast on it
GET /api/decisions/{key}/document — the motion or bill it decided on
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import parse_choices
from lawgraph.api.schemas.decisions import (
    DecisionDTO,
    DecisionFacets,
    DecisionListResponse,
    DecisionSummaryDTO,
)
from lawgraph.api.schemas.documents import DocumentTextResponse
from lawgraph.api.schemas.dossiers import DOSSIER_NUMBER_PATTERN
from lawgraph.core.tk_records import DECISION_KINDS, VOTE_AGAINST, VOTE_FOR
from lawgraph.db import ArangoStore
from lawgraph.db.queries.decisions import (
    DecisionFilters,
    get_decision_detail,
    get_decision_document,
    get_decisions,
)
from lawgraph.db.queries.documents import get_document_links

router = APIRouter()


# ``vote`` as the parameter takes it -> ``meta.choice`` on the VOTED edge
_VOTE_CHOICES = {"voor": VOTE_FOR, "tegen": VOTE_AGAINST}


@router.get(
    "",
    response_model=DecisionListResponse,
    summary="Decision browser",
    description=(
        "A page of decisions — one per Besluit — newest first, optionally "
        "filtered by kind, outcome, party (and how it voted), chamber, dossier, date "
        "and subject. ``total`` is the absolute count, independent of ``limit``. "
        "``facets`` counts the decisions under the filters: per ``kind`` (without the "
        "kind filter), per outcome ``passed`` (without the passed filter) and per day "
        "(under all filters)."
    ),
    tags=["decisions"],
)
def list_decisions(
    store: Annotated[ArangoStore, Depends(get_store)],
    kind: Annotated[
        str | None,
        Query(
            description="Comma-separated: `motie`, `amendement`, `wetsvoorstel`, "
            "`overig`."
        ),
    ] = None,
    passed: Annotated[
        bool | None, Query(description="Only decisions that carried, or did not.")
    ] = None,
    party: Annotated[
        str | None, Query(description="Only decisions this party voted on.")
    ] = None,
    vote: Annotated[
        Literal["voor", "tegen"] | None,
        Query(description="With `party`: only decisions it voted for, or against."),
    ] = None,
    chamber: Annotated[str | None, Query(description="'TK' or 'EK'.")] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="Only decisions on this dossier number, e.g. 29684.",
            pattern=DOSSIER_NUMBER_PATTERN,
        ),
    ] = None,
    date_from: Annotated[
        dt.date | None,
        Query(alias="from", description="Voted on or after this date, YYYY-MM-DD."),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Voted on or before this date, YYYY-MM-DD."),
    ] = None,
    q: Annotated[
        str | None,
        Query(description="A part of the subject, in any case."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DecisionListResponse:
    if vote is not None and not party:
        raise HTTPException(status_code=422, detail="`vote` needs a `party`.")
    filters = DecisionFilters(
        kinds=parse_choices(kind, DECISION_KINDS, "kind"),
        passed=passed,
        party=party,
        choice=_VOTE_CHOICES[vote] if vote else None,
        chamber=chamber,
        dossier=dossier,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        q=(q or "").strip() or None,
    )
    raw = get_decisions(store, filters, limit=limit, offset=offset)
    return DecisionListResponse(
        total=int(raw.get("total") or 0),
        items=[DecisionSummaryDTO(**row) for row in raw.get("items") or []],
        facets=DecisionFacets(**(raw.get("facets") or {})),
    )


@router.get(
    "/{key}",
    response_model=DecisionDTO,
    summary="Decision detail",
    description=(
        "One decision with every vote cast on it — per member on a roll-call, "
        "per faction otherwise."
    ),
    tags=["decisions"],
)
def get_decision(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DecisionDTO:
    doc = get_decision_detail(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Decision '{key}' not found.")
    return DecisionDTO.from_document(doc)


@router.get(
    "/{key}/document",
    response_model=DocumentTextResponse,
    summary="The document behind a decision",
    description=(
        "The motion, amendment or bill this decision was about, with its full text."
    ),
    tags=["decisions"],
)
def get_decision_document_route(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DocumentTextResponse:
    decision = get_decision_detail(store, key)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"Decision '{key}' not found.")
    document = get_decision_document(store, decision)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"No document resolvable for decision '{key}'.",
        )
    return DocumentTextResponse.from_document(
        document, get_document_links(store, document["_id"])
    )
