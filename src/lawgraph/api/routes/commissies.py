"""API routes for parliamentary committees and members.

GET /api/commissies                       — list all committees with active dossier counts
GET /api/commissies/{slug}                — committee detail with members and recent activiteiten
GET /api/leden/{key}                      — member detail
GET /api/leden/{key}/votes                — paginated voting record
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_actor_touched_instruments,
    get_all_commissies,
    get_all_commissies_with_leden,
    get_all_fracties,
    get_all_leden,
    get_commissie_detail,
    get_lid_votes,
)
from lawgraph.api.schemas import (
    CommissieDetailDTO,
    CommissieDTO,
    CommissieWithLedenDTO,
    FractieDetailDTO,
    FractieDTO,
    LidDTO,
    LidVoteEntryDTO,
    LidVotesResponse,
    TouchedInstrumentDTO,
    TouchedInstrumentsResponse,
)
from lawgraph.db import ArangoStore

router = APIRouter()
leden_router = APIRouter()
fracties_router = APIRouter()


# Bulk commissies-with-leden is a slow-moving signal (committee membership
# changes infrequently). Cache the materialised response for 60 s so cold
# clicks on the parliamentary Lagen layer don't all pay the AQL.
_BULK_CACHE: dict[str, tuple[float, Any]] = {}
_BULK_TTL_SECONDS = 60.0


def _cache_get(key: str) -> Any | None:
    entry = _BULK_CACHE.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        _BULK_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    _BULK_CACHE[key] = (time.monotonic() + _BULK_TTL_SECONDS, value)


@router.get(
    "",
    response_model=list[CommissieDTO],
    summary="Alle commissies",
    description="Geeft alle parlementaire commissies met het aantal actieve dossiers.",
    tags=["commissies"],
)
def list_commissies(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[CommissieDTO]:
    docs = get_all_commissies(store)
    return [
        CommissieDTO.from_document(
            d, active_dossier_count=d.get("active_dossier_count", 0)
        )
        for d in docs
    ]


@router.get(
    "/with-leden",
    response_model=list[CommissieWithLedenDTO],
    summary="Alle commissies met hun leden",
    description=(
        "Bulk-variant van /api/commissies: één query levert elke commissie "
        "met de bijbehorende leden. Bedoeld voor de parlementaire Lagen-load "
        "die anders 130+ losse /api/commissies/{slug} calls zou doen."
    ),
    tags=["commissies"],
)
def list_commissies_with_leden(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[CommissieWithLedenDTO]:
    cached = _cache_get("with_leden")
    if cached is not None:
        return cached
    docs = get_all_commissies_with_leden(store)
    response = [CommissieWithLedenDTO.from_document(d) for d in docs]
    _cache_set("with_leden", response)
    return response


@router.get(
    "/{slug}",
    response_model=CommissieDetailDTO,
    summary="Commissie detail",
    description=(
        "Detail van één commissie, inclusief leden en recente behandelde dossiers. "
        "Standaard worden alleen **huidige** leden getoond (``current_only=true``): "
        "LID_VAN-kanten zonder ``geldig_tot`` of met een toekomstige ``geldig_tot``. "
        "Gebruik ``?current_only=false`` voor alle historische leden."
    ),
    tags=["commissies"],
)
def get_commissie(
    slug: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    current_only: Annotated[
        bool,
        Query(
            description="Alleen huidige commissieleden (geldig_tot ontbreekt of in de toekomst)"
        ),
    ] = True,
) -> CommissieDetailDTO:
    doc = get_commissie_detail(store, slug, current_only=current_only)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Commissie '{slug}' not found.")
    return CommissieDetailDTO.from_detail_document(doc)


@leden_router.get(
    "",
    response_model=list[LidDTO],
    summary="Alle Kamerleden",
    description=(
        "Lijst van Kamerleden, optioneel gefilterd op partij of naam. "
        "Standaard alleen leden met een fractielidmaatschap (de ~800 ooit-MP's); "
        "pas ?include_all=true toe om ook ministers en niet-MP-personen te tonen."
    ),
    tags=["leden"],
)
def list_leden(
    store: Annotated[ArangoStore, Depends(get_store)],
    partij: Annotated[
        str | None, Query(description="Partij (afkorting of naam)")
    ] = None,
    actief: Annotated[bool | None, Query(description="Alleen actieve leden")] = None,
    q: Annotated[
        str | None, Query(description="Naam-substring (case-insensitive)")
    ] = None,
    include_all: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[LidDTO]:
    docs = get_all_leden(
        store,
        partij=partij,
        actief=actief,
        q=q,
        include_all=include_all,
        limit=limit,
        offset=offset,
    )
    return [LidDTO.from_document(d) for d in docs]


@leden_router.get(
    "/{key}",
    response_model=LidDTO,
    summary="Lid detail",
    description="Geeft de basisgegevens van een Kamerlid of minister.",
    tags=["leden"],
)
def get_lid(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> LidDTO:
    node = store.get_node("leden", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Lid '{key}' not found.")
    doc = {
        "_id": node.id,
        "_key": node.key,
        "type": node.type.value,
        "labels": node.labels,
        "props": node.props,
    }
    return LidDTO.from_document(doc)


@leden_router.get(
    "/{key}/votes",
    response_model=LidVotesResponse,
    summary="Stemmingsgeschiedenis van een lid",
    description=(
        "Gepagineerd stemoverzicht van een Kamerlid. Per stemming wordt de "
        "partij van dat lid op het moment van stemmen geresolveerd via "
        "``fractielidmaatschappen``, zodat historische stemmen correct "
        "worden toegeschreven aan de toenmalige partij."
    ),
    tags=["leden"],
)
def get_lid_voting_record(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> LidVotesResponse:
    node = store.get_node("leden", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Lid '{key}' not found.")
    lid_id = node.id
    votes = get_lid_votes(store, lid_id or "", limit=limit)
    return LidVotesResponse(
        lid_id=lid_id,
        total=len(votes),
        votes=[LidVoteEntryDTO(**v) for v in votes],
    )


def _touched_instrument_row_to_dto(row: dict) -> TouchedInstrumentDTO:
    """Adapt the AQL row shape to the strict DTO field names.

    The AQL emits ``instrument_id``/``instrument_key``; the strict DTO uses
    the canonical ``id``/``key`` everywhere — same fix as cited_articles.
    """
    return TouchedInstrumentDTO(
        id=row.get("instrument_id") or row.get("id"),
        key=row.get("instrument_key") or row.get("key"),
        display_name=row.get("display_name"),
        title=row.get("title"),
        short_title=row.get("short_title"),
        citation_title=row.get("citation_title"),
        bwb_id=row.get("bwb_id"),
        celex=row.get("celex"),
        count=int(row.get("count") or 0),
    )


@leden_router.get(
    "/{key}/touched-instruments",
    response_model=TouchedInstrumentsResponse,
    summary="Top wetten die dit lid het vaakst raakt",
    description=(
        "Top-N wetten waar dit lid via wetsvoorstellen, amendementen of moties "
        "wijzigingen op heeft ingediend, gerangschikt op aantal kamerstukken. "
        "``actor_id`` is het Arango _id van het lid; ``items`` zijn de "
        "betreffende wetten met een tellertje per wet."
    ),
    tags=["leden"],
)
def get_lid_touched_instruments_route(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TouchedInstrumentsResponse:
    node = store.get_node("leden", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Lid '{key}' not found.")
    lid_id = node.id or ""
    items = get_actor_touched_instruments(store, lid_id, limit=limit)
    return TouchedInstrumentsResponse(
        actor_id=lid_id,
        total=len(items),
        items=[_touched_instrument_row_to_dto(r) for r in items],
    )


@fracties_router.get(
    "",
    response_model=list[FractieDTO],
    summary="Alle fracties",
    description=(
        "Lijst van Tweede Kamer-fracties (politieke partijen), met het aantal "
        "gekoppelde leden. Standaard actieve fracties eerst; "
        "optionele filters op `actief` en vrije-tekstzoek (`q`) op naam/afkorting."
    ),
    tags=["fracties"],
)
def list_fracties(
    store: Annotated[ArangoStore, Depends(get_store)],
    actief: Annotated[
        bool | None, Query(description="Alleen (in)actieve fracties")
    ] = None,
    q: Annotated[
        str | None, Query(description="Naam/afkorting (case-insensitive)")
    ] = None,
) -> list[FractieDTO]:
    docs = get_all_fracties(store, actief=actief, q=q)
    return [
        FractieDTO.from_document(d, member_count=int(d.get("member_count") or 0))
        for d in docs
    ]


@fracties_router.get(
    "/{key}",
    response_model=FractieDetailDTO,
    summary="Fractie detail",
    description=(
        "Geeft één fractie-node terug met identifier, labels en de raw "
        "``props`` zoals opgeslagen in de graph. Voor gestructureerde "
        "fractie-metadata zie ``/api/fracties`` (lijst-endpoint) — dit "
        "detail-endpoint is bewust een doorgeefluik."
    ),
    tags=["fracties"],
)
def get_fractie(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> FractieDetailDTO:
    node = store.get_node("fracties", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Fractie '{key}' not found.")
    return FractieDetailDTO(
        id=node.id or "",
        key=node.key or "",
        type=node.type.value,
        labels=list(node.labels or []),
        props=node.props,
    )


@fracties_router.get(
    "/{key}/touched-instruments",
    response_model=TouchedInstrumentsResponse,
    summary="Top wetten die deze fractie het vaakst raakt",
    description=(
        "Top-N wetten waar deze fractie via wetsvoorstellen, amendementen "
        "of moties wijzigingen op heeft ingediend. Zelfde response-shape "
        "als de leden-variant; ``actor_id`` is het Arango _id van de "
        "fractie."
    ),
    tags=["fracties"],
)
def get_fractie_touched_instruments_route(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TouchedInstrumentsResponse:
    node = store.get_node("fracties", key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Fractie '{key}' not found.")
    fractie_id = node.id or ""
    items = get_actor_touched_instruments(store, fractie_id, limit=limit)
    return TouchedInstrumentsResponse(
        actor_id=fractie_id,
        total=len(items),
        items=[_touched_instrument_row_to_dto(r) for r in items],
    )
