"""Committee, member and faction endpoints.

GET /api/committees                          — every committee
GET /api/committees/with-members             — every committee with its members
GET /api/committees/{slug}                   — one committee in full
GET /api/committees/{slug}/activities        — the activities it leads
GET /api/members                             — members of parliament
GET /api/members/{key}                       — one member
GET /api/members/{key}/votes                 — how a member voted
GET /api/members/{key}/dossiers              — the dossiers a member authored in
GET /api/members/{key}/touched-instruments   — the laws a member changes most
GET /api/factions                            — parliamentary parties
GET /api/factions/{key}                      — one party
GET /api/factions/{key}/dossiers             — the dossiers a party authored in
GET /api/factions/{key}/touched-instruments  — the laws a party changes most
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.committees import (
    ActorDossierDTO,
    ActorDossiersResponse,
    CommitteeActivitiesResponse,
    CommitteeActivityDTO,
    CommitteeDetailDTO,
    CommitteeDTO,
    CommitteeWithMembersDTO,
    FactionDetailDTO,
    FactionDTO,
    MemberDetailDTO,
    MemberDTO,
    MemberVoteDTO,
    MemberVotesResponse,
    TouchedInstrumentDTO,
    TouchedInstrumentsResponse,
)
from lawgraph.config.constants import COLLECTION_FACTIONS, COLLECTION_MEMBERS
from lawgraph.core.cache import _MISSING, TTLCache
from lawgraph.db import ArangoStore
from lawgraph.db.queries.committees import (
    get_actor_dossiers,
    get_actor_touched_instruments,
    get_committee_activities,
    get_committee_detail,
    get_committees,
    get_committees_with_members,
    get_factions,
    get_member_votes,
    get_members,
)
from lawgraph.db.queries.dossiers import enrich_dossier_docs

router = APIRouter()
members_router = APIRouter()
factions_router = APIRouter()

# Committee membership changes rarely, and the bulk shape is what the
# parliamentary layer loads first, so a short cache spares every cold click
# the aggregation.
_bulk_cache: TTLCache[str, Any] = TTLCache(maxsize=32)

# A faction's dossiers walk every AUTHORED edge of every member it ever had, so a page
# is worth keeping for the next click.
_faction_dossiers_cache: TTLCache[tuple[str, int, int], ActorDossiersResponse] = (
    TTLCache(maxsize=64)
)


@router.get(
    "",
    response_model=list[CommitteeDTO],
    summary="All committees",
    description="Every parliamentary committee with its number of open dossiers.",
    tags=["committees"],
)
def list_committees(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[CommitteeDTO]:
    return [
        CommitteeDTO.from_document(
            doc, active_dossier_count=doc.get("active_dossier_count") or 0
        )
        for doc in get_committees(store)
    ]


@router.get(
    "/with-members",
    response_model=list[CommitteeWithMembersDTO],
    summary="All committees with their members",
    description=(
        "One query returns every committee with its current members. The "
        "alternative is a separate call per committee, 130 times over."
    ),
    tags=["committees"],
)
def list_committees_with_members(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> list[CommitteeWithMembersDTO]:
    cached = _bulk_cache.get("with_members")
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]
    response = [
        CommitteeWithMembersDTO.from_document(doc)
        for doc in get_committees_with_members(store)
    ]
    _bulk_cache.set("with_members", response)
    return response


@router.get(
    "/{slug}",
    response_model=CommitteeDetailDTO,
    summary="Committee detail",
    description=(
        "One committee with its members and a page of the dossiers it leads, "
        "newest first; ``dossier_total`` is the absolute count. By default "
        "only current members are returned — a seat with no end date, or an "
        "end date still ahead. Pass ``?current_only=false`` for every member "
        "the committee ever had. ``limit``, ``offset`` and ``status`` page and "
        "filter the dossiers."
    ),
    tags=["committees"],
)
def get_committee(
    slug: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    current_only: Annotated[
        bool, Query(description="Only members currently seated on this committee.")
    ] = True,
    status: Annotated[
        Literal["open", "closed"] | None,
        Query(description="Only the open or only the closed dossiers."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Dossiers per page.")] = 100,
    offset: Annotated[int, Query(ge=0, description="Dossiers to skip.")] = 0,
) -> CommitteeDetailDTO:
    doc = get_committee_detail(
        store,
        slug,
        current_only=current_only,
        status=status,
        limit=limit,
        offset=offset,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Committee '{slug}' not found.")
    return CommitteeDetailDTO.from_detail_document(doc)


@router.get(
    "/{slug}/activities",
    response_model=CommitteeActivitiesResponse,
    summary="Committee activities",
    description=(
        "The activities (debates, hearings) a committee leads, newest first, "
        "with the dossiers on their agenda. ``total`` is the absolute count."
    ),
    tags=["committees"],
)
def list_committee_activities(
    slug: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CommitteeActivitiesResponse:
    raw = get_committee_activities(store, slug, limit=limit, offset=offset)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Committee '{slug}' not found.")
    return CommitteeActivitiesResponse(
        total=int(raw.get("total") or 0),
        items=[CommitteeActivityDTO(**item) for item in raw.get("items") or []],
    )


@members_router.get(
    "",
    response_model=list[MemberDTO],
    summary="Members of parliament",
    description=(
        "Members of parliament, optionally filtered by party or name. By "
        "default only people who ever held a seat; pass "
        "``?include_all=true`` to include ministers and other non-members."
    ),
    tags=["members"],
)
def list_members(
    store: Annotated[ArangoStore, Depends(get_store)],
    party: Annotated[
        str | None, Query(description="Party abbreviation or name.")
    ] = None,
    active: Annotated[
        bool | None, Query(description="Only members currently seated.")
    ] = None,
    q: Annotated[str | None, Query(description="Name substring.")] = None,
    include_all: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MemberDTO]:
    docs = get_members(
        store,
        party=party,
        active=active,
        q=q,
        include_all=include_all,
        limit=limit,
        offset=offset,
    )
    return [MemberDTO.from_document(d) for d in docs]


@members_router.get(
    "/{key}",
    response_model=MemberDetailDTO,
    summary="Member detail",
    description=(
        "One member of parliament or minister, with the posts they held in a cabinet "
        "(`government_functions`, from Wikidata)."
    ),
    tags=["members"],
)
def get_member(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> MemberDetailDTO:
    node = _node_or_404(store, COLLECTION_MEMBERS, key, "Member")
    return MemberDetailDTO.from_document(_as_document(node))


@members_router.get(
    "/{key}/votes",
    response_model=MemberVotesResponse,
    summary="How a member voted",
    description=(
        "A member's voting record, newest first. A roll-call names the member "
        "directly; any other vote is their faction's, counted only for the "
        "period they belonged to it, so historic votes keep the party they "
        "were cast under."
    ),
    tags=["members"],
)
def list_member_votes(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MemberVotesResponse:
    node = _node_or_404(store, COLLECTION_MEMBERS, key, "Member")
    member_id = node.arango_id or ""
    votes = get_member_votes(store, member_id, limit=limit)
    return MemberVotesResponse(
        member_id=member_id,
        count=len(votes),
        votes=[MemberVoteDTO(**v) for v in votes],
    )


@members_router.get(
    "/{key}/dossiers",
    response_model=ActorDossiersResponse,
    summary="Dossiers a member authored in",
    description=(
        "The dossiers in which this member signed or submitted documents "
        "(``AUTHORED``), newest opened first. Each dossier carries the roles "
        "the member had there, the functions and capacities they signed in "
        "(``kamerlid``, ``bewindspersoon``, ``overig``) and the number of documents. "
        "``total`` is the absolute count."
    ),
    tags=["members"],
)
def list_member_dossiers(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActorDossiersResponse:
    node = _node_or_404(store, COLLECTION_MEMBERS, key, "Member")
    return _actor_dossiers(store, node.arango_id or "", limit, offset)


@members_router.get(
    "/{key}/touched-instruments",
    response_model=TouchedInstrumentsResponse,
    summary="The laws this member changes most",
    description=(
        "The laws this member proposed changes to through bills, amendments "
        "or motions, ranked by how many documents did so."
    ),
    tags=["members"],
)
def list_member_touched_instruments(
    key: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TouchedInstrumentsResponse:
    node = _node_or_404(store, COLLECTION_MEMBERS, key, "Member")
    return _touched_instruments(store, node.arango_id or "", limit)


@factions_router.get(
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
    store: Annotated[ArangoStore, Depends(get_store)],
    active: Annotated[
        bool | None, Query(description="Only (in)active parties.")
    ] = None,
    q: Annotated[str | None, Query(description="Name or abbreviation.")] = None,
) -> list[FactionDTO]:
    return [
        FactionDTO.from_document(doc, member_count=int(doc.get("member_count") or 0))
        for doc in get_factions(store, active=active, q=q)
    ]


@factions_router.get(
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
    store: Annotated[ArangoStore, Depends(get_store)],
) -> FactionDetailDTO:
    node = _node_or_404(store, COLLECTION_FACTIONS, key, "Faction")
    return FactionDetailDTO(
        id=node.arango_id or "",
        key=node.key or "",
        type=node.type.value,
        labels=list(node.labels or []),
        props=node.props,
    )


@factions_router.get(
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
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActorDossiersResponse:
    node = _node_or_404(store, COLLECTION_FACTIONS, key, "Faction")
    cache_key = (node.arango_id or "", limit, offset)
    cached = _faction_dossiers_cache.get(cache_key)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]
    response = _actor_dossiers(store, node.arango_id or "", limit, offset)
    _faction_dossiers_cache.set(cache_key, response)
    return response


@factions_router.get(
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
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TouchedInstrumentsResponse:
    node = _node_or_404(store, COLLECTION_FACTIONS, key, "Faction")
    return _touched_instruments(store, node.arango_id or "", limit)


def _node_or_404(store: ArangoStore, collection: str, key: str, label: str) -> Any:
    node = store.get_node(collection, key)
    if node is None:
        raise HTTPException(status_code=404, detail=f"{label} '{key}' not found.")
    return node


def _as_document(node: Any) -> dict[str, Any]:
    return {
        "_id": node.arango_id,
        "_key": node.key,
        "type": node.type.value,
        "labels": node.labels,
        "props": node.props,
    }


def _touched_instruments(
    store: ArangoStore, actor_id: str, limit: int
) -> TouchedInstrumentsResponse:
    items = get_actor_touched_instruments(store, actor_id, limit=limit)
    return TouchedInstrumentsResponse(
        actor_id=actor_id,
        count=len(items),
        items=[TouchedInstrumentDTO(**item) for item in items],
    )


def _actor_dossiers(
    store: ArangoStore, actor_id: str, limit: int, offset: int
) -> ActorDossiersResponse:
    raw = get_actor_dossiers(store, actor_id, limit=limit, offset=offset)
    rows = raw.get("items") or []
    enrich_dossier_docs(store, [row["dossier"] for row in rows])
    return ActorDossiersResponse(
        actor_id=actor_id,
        total=int(raw.get("total") or 0),
        items=[ActorDossierDTO.from_row(row) for row in rows],
    )
