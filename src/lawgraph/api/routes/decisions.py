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
from lawgraph.api.schemas.common import dossier_names_of
from lawgraph.api.schemas.decisions import (
    DecisionDTO,
    DecisionFacets,
    DecisionListResponse,
    DecisionSummaryDTO,
)
from lawgraph.api.schemas.documents import DocumentTextResponse
from lawgraph.api.schemas.dossiers import DOSSIER_NUMBER_PATTERN
from lawgraph.core.tk_records import VOTE_AGAINST, VOTE_FOR
from lawgraph.db import GraphStore
from lawgraph.db.queries.committees import load_member_slugs
from lawgraph.db.queries.decisions import (
    DecisionFilters,
    get_decision_detail,
    get_decision_document,
    get_decisions,
    motion_dictums,
)
from lawgraph.db.queries.documents import get_document_links
from lawgraph.db.queries.dossiers import load_dossier_names

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
        "kind filter; with how many carried and did not), per outcome ``passed`` "
        "(without the passed filter), per day and per year (under all filters), and with "
        "``party_votes`` how the factions asked voted on them."
    ),
    tags=["decisions"],
)
def list_decisions(
    store: Annotated[GraphStore, Depends(get_store)],
    kind: Annotated[
        str | None,
        Query(
            description="Comma-separated kinds (``Zaak.Soort`` as the Kamer writes it): "
            "``Motie``, ``Amendement``, ``Wetgeving``, ..."
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
        list[str] | None,
        Query(
            description="Words of the subject, in any case: each from the start of a "
            "word, one of at most four characters as a whole word. Repeat it for "
            "decisions that hold any of them (``q=AI&q=kunstmatige intelligentie``)."
        ),
    ] = None,
    party_votes: Annotated[
        str | None,
        Query(
            description="Comma-separated faction keys, or ``all`` for every faction "
            "that voted on one: ``facets.party_votes`` says how each voted on the "
            "decisions under the filters (``voor``, ``tegen``, ``none``; in all, per "
            "kind and per year). Keeps no decision out, unlike ``party``."
        ),
    ] = None,
    coalition: Annotated[
        Literal["together", "split", "wissel", "carried", "decisive"] | None,
        Query(
            description="Only the votes of the Tweede Kamer on which the coalition voted "
            "`together`, `split` (no wisselmeerderheid) or as a `wissel`, or which it "
            "`carried` or was `decisive` on."
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DecisionListResponse:
    if vote is not None and not party:
        raise HTTPException(status_code=422, detail="`vote` needs a `party`.")
    filters = DecisionFilters(
        kinds=parse_choices(kind, None, "kind"),
        passed=passed,
        party=party,
        choice=_VOTE_CHOICES[vote] if vote else None,
        chamber=chamber,
        dossier=dossier,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        q=tuple(word.strip() for word in q or () if word.strip()),
        party_votes=tuple(
            party.strip() for party in (party_votes or "").split(",") if party.strip()
        ),
        coalition=coalition,
    )
    raw = get_decisions(store, filters, limit=limit, offset=offset)
    names = load_dossier_names(store)
    return DecisionListResponse(
        total=int(raw.get("total") or 0),
        items=[
            DecisionSummaryDTO(
                **row,
                dossiers=dossier_names_of(row.get("dossier_numbers") or [], names),
            )
            for row in raw.get("items") or []
        ],
        facets=DecisionFacets(**(raw.get("facets") or {})),
        partial=bool(raw.get("partial")),
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
    store: Annotated[GraphStore, Depends(get_store)],
) -> DecisionDTO:
    doc = get_decision_detail(store, key)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Decision '{key}' not found.")
    (dictum,) = motion_dictums(store, [doc["props"]])
    dto = DecisionDTO.from_document(
        doc, load_dossier_names(store), load_member_slugs(store)
    )
    return dto.model_copy(update={"dictum": dictum})


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
    store: Annotated[GraphStore, Depends(get_store)],
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
        document,
        get_document_links(store, document["_id"]),
        slugs=load_member_slugs(store),
    )
