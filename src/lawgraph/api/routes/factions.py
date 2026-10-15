"""Faction endpoints.

GET /api/factions                            — parliamentary parties
GET /api/factions/{key}                      — one party
GET /api/factions/{key}/dossiers             — the dossiers a party authored in
GET /api/factions/{key}/votes                — how a faction of the Eerste Kamer voted
GET /api/factions/{key}/touched-instruments  — the laws a party changes most
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.actors import actor_dossiers, touched_instruments
from lawgraph.api.dependencies import get_store
from lawgraph.api.params import ActiveFrom, ActiveTo, ListChamber, iso_day
from lawgraph.api.schemas.actors import (
    ActorDossiersResponse,
    TouchedInstrumentsResponse,
)
from lawgraph.api.schemas.common import dossier_names_of
from lawgraph.api.schemas.ek_source import EkSourceDTO
from lawgraph.api.schemas.factions import (
    EkFactionVoteDTO,
    EkFactionVotesResponse,
    FactionDetailDTO,
    FactionDTO,
)
from lawgraph.config.constants import COLLECTION_FACTIONS
from lawgraph.config.settings import EK_ATTRIBUTION
from lawgraph.core.ek_votes import VOTES_PATH
from lawgraph.core.official_urls import ek_url
from lawgraph.db import GraphStore
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.factions import get_ek_faction_votes, get_factions
from lawgraph.db.queries.not_found import require_node
from lawgraph.db.version_cache import cached

router = APIRouter()


@router.get(
    "",
    response_model=list[FactionDTO],
    summary="All factions",
    description=(
        "The parliamentary parties with their member counts, seated ones "
        "first. Filter on ``active`` or search names and abbreviations with "
        "``q``."
    ),
    tags=["factions"],
)
def list_factions(
    store: Annotated[GraphStore, Depends(get_store)],
    active: Annotated[
        bool | None, Query(description="Only (in)active parties.")
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description="A part of the name or abbreviation, in any case, with or "
            "without accents."
        ),
    ] = None,
    chamber: ListChamber = "TK",
    active_from: ActiveFrom = None,
    active_to: ActiveTo = None,
) -> list[FactionDTO]:
    return [
        FactionDTO.from_document(doc, member_count=int(doc.get("member_count") or 0))
        for doc in get_factions(
            store,
            active=active,
            q=q,
            chamber=chamber,
            active_from=iso_day(active_from),
            active_to=iso_day(active_to),
        )
    ]


@router.get(
    "/{key}",
    response_model=FactionDetailDTO,
    summary="Faction detail",
    description=(
        "One faction node with its identifiers and raw props. For structured "
        "faction metadata use the list endpoint."
    ),
    tags=["factions"],
)
def get_faction(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> FactionDetailDTO:
    faction = require_node(store, COLLECTION_FACTIONS, key, "Faction")
    return FactionDetailDTO(
        id=faction["_id"],
        key=faction["_key"],
        type=faction["type"],
        labels=faction["labels"],
        props=faction["props"],
    )


@router.get(
    "/{key}/dossiers",
    response_model=ActorDossiersResponse,
    summary="Dossiers a faction authored in",
    description=(
        "The dossiers in which members of this faction signed or submitted "
        "documents while they belonged to it, newest opened first. Same shape "
        "as the member variant; ``roles`` and ``document_count`` cover all "
        "those members."
    ),
    tags=["factions"],
)
def list_faction_dossiers(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActorDossiersResponse:
    faction_id = require_node(store, COLLECTION_FACTIONS, key, "Faction")["_id"]
    # every paper every member of the faction ever signed: kept for the next click, per
    # data version (the date of a paper of any kind is read from ``nodes``)
    return cached(
        store,
        ("faction dossiers", faction_id, limit, offset),
        lambda: actor_dossiers(store, faction_id, limit, offset),
    )


@router.get(
    "/{key}/votes",
    response_model=EkFactionVotesResponse,
    summary="How a faction of the Eerste Kamer voted",
    description=(
        "The votes of the Eerste Kamer that name this faction (its list of votes on "
        "bills, since June 2015), newest first, with the faction's choice as the list "
        "names it (``voor``, ``tegen``, ``aantekening gevraagd``) and the counts per "
        "choice. ``bill_decision`` tells the vote on the bill from one on a motion on it. "
        "Only a faction of the Eerste Kamer (``chamber`` ``EK``): the Tweede Kamer's "
        "votes per faction are ``/api/decisions?party=``."
    ),
    tags=["factions"],
)
def list_faction_votes(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    date_from: Annotated[
        dt.date | None, Query(alias="from", description="On or after, YYYY-MM-DD.")
    ] = None,
    date_to: Annotated[
        dt.date | None, Query(alias="to", description="On or before, YYYY-MM-DD.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EkFactionVotesResponse:
    props = require_node(store, COLLECTION_FACTIONS, key, "Faction")["props"]
    if props.get("chamber") != "EK":
        raise HTTPException(
            status_code=422,
            detail="Only a faction of the Eerste Kamer; for the Tweede Kamer use "
            "/api/decisions?party=.",
        )
    raw = get_ek_faction_votes(
        store,
        props.get("abbreviation") or "",
        from_date=iso_day(date_from),
        to_date=iso_day(date_to),
        limit=limit,
        offset=offset,
    )
    names = load_dossier_names(store)
    return EkFactionVotesResponse(
        faction_key=key,
        total=int(raw.get("total") or 0),
        counts=raw.get("counts") or {},
        items=[
            EkFactionVoteDTO(
                **item,
                dossiers=dossier_names_of(item.get("dossier_numbers") or [], names),
            )
            for item in raw.get("items") or []
        ],
        source=EkSourceDTO(
            url=ek_url(VOTES_PATH),
            retrieved_on=None,  # each vote has its own day of reading
            composition_date=None,
            data_since=None,
            attribution=EK_ATTRIBUTION,
        ),
    )


@router.get(
    "/{key}/touched-instruments",
    response_model=TouchedInstrumentsResponse,
    summary="The laws this faction changes most",
    description=(
        "The laws this faction proposed changes to through bills, amendments "
        "or motions. Same shape as the member variant."
    ),
    tags=["factions"],
)
def list_faction_touched_instruments(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TouchedInstrumentsResponse:
    faction = require_node(store, COLLECTION_FACTIONS, key, "Faction")
    return touched_instruments(store, faction["_id"], limit)
