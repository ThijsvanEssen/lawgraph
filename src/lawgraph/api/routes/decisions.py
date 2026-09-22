"""Decision (vote) endpoints.

GET /api/decisions            — the vote browser
GET /api/decisions/{key}      — one decision with every vote cast on it
GET /api/decisions/{key}/document — the motion or bill it decided on
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.decisions import (
    get_decision_detail,
    get_decision_document,
    get_decisions,
)
from lawgraph.api.queries.documents import get_document_links
from lawgraph.api.schemas.decisions import (
    DecisionDTO,
    DecisionListResponse,
    DecisionSummaryDTO,
)
from lawgraph.api.schemas.documents import DocumentTextResponse
from lawgraph.api.schemas.dossiers import DOSSIER_NUMBER_PATTERN
from lawgraph.db import ArangoStore

router = APIRouter()


@router.get(
    "",
    response_model=DecisionListResponse,
    summary="Decision browser",
    description=(
        "A page of decisions — one per Besluit — newest first, optionally "
        "filtered by outcome, party, chamber or dossier. ``total`` is the "
        "absolute count, independent of ``limit``."
    ),
    tags=["decisions"],
)
def list_decisions(
    store: Annotated[ArangoStore, Depends(get_store)],
    passed: Annotated[
        bool | None, Query(description="Only decisions that carried, or did not.")
    ] = None,
    party: Annotated[
        str | None, Query(description="Only decisions this party voted on.")
    ] = None,
    chamber: Annotated[str | None, Query(description="'TK' or 'EK'.")] = None,
    dossier: Annotated[
        str | None,
        Query(
            description="Only decisions on this dossier number, e.g. 29684.",
            pattern=DOSSIER_NUMBER_PATTERN,
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DecisionListResponse:
    raw = get_decisions(
        store,
        passed=passed,
        party=party,
        chamber=chamber,
        dossier=dossier,
        limit=limit,
        offset=offset,
    )
    return DecisionListResponse(
        total=int(raw.get("total") or 0),
        items=[DecisionSummaryDTO(**row) for row in raw.get("items") or []],
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
