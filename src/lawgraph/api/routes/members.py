"""Member endpoints.

GET /api/members                             — members of parliament
GET /api/members/{key}                       — one member
GET /api/members/{key}/votes                 — how a member voted
GET /api/members/{key}/documents             — the newest papers a member signed
GET /api/members/{key}/dossiers              — the dossiers a member authored in
GET /api/members/{key}/touched-instruments   — the laws a member changes most
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.actors import actor_dossiers, touched_instruments
from lawgraph.api.dependencies import get_store
from lawgraph.api.params import (
    ActiveFrom,
    ActiveTo,
    ActorDossierSort,
    ListChamber,
    ListLimit,
    MemberListLimit,
    PageLimit,
    TopLimit,
)
from lawgraph.api.schemas.actors import (
    ActorDossiersResponse,
    TouchedInstrumentsResponse,
)
from lawgraph.api.schemas.members import (
    MemberDetailDTO,
    MemberDocumentsResponse,
    MemberDTO,
    MemberVoteDTO,
    MemberVotesResponse,
)
from lawgraph.api.schemas.nodes import NeighborDTO
from lawgraph.config.constants import COLLECTION_MEMBERS
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.member_authored import get_signed
from lawgraph.db.queries.member_votes import get_member_votes
from lawgraph.db.queries.members import (
    get_ek_members,
    get_member_committees,
    get_members,
)
from lawgraph.db.queries.not_found import require_node

router = APIRouter()


@router.get(
    "",
    response_model=list[MemberDTO],
    summary="Members of parliament",
    description=(
        "Members of parliament, optionally filtered by party or name, each with the "
        "posts they held in a cabinet (``government_functions``). By default only "
        "people who ever held a seat; ``?include_all=true`` includes ministers and "
        "other non-members, ``capacity=bewindspersoon`` keeps everyone who held a post "
        "in a cabinet and ``cabinet`` those who held one in that cabinet. A record "
        "without a name is never listed."
        "\n\n"
        "members, each with its `government_functions` (filter `party` (the current "
        "party or any faction of the timeline; with `active=true` the faction they sit "
        "for now, so a member who left it for another is not counted), `active`, `q` "
        "(a part of the name, in any case and with or without accents: `yesilgoz` "
        "finds Yeşilgöz), `slug` (the one member of that slug, whoever they are); "
        "`sort` `name` (default) or `family_name`: by surname, then tussenvoegsel, as "
        "the Kamer lists its members, those without a surname in the source last; "
        "ministers only with `include_all`, `capacity=bewindspersoon` (everyone who "
        "held a post in a cabinet) or `cabinet` (a cabinet key: who held a post in "
        "it); a record without a name is never listed); a member's votes, a faction "
        "vote counted only for the period they belonged to it, each with `vote_source` "
        "(`member`: their own, on a roll-call; `faction`: their faction's) and the "
        "`faction_key` and `party` of the faction they sat in on its date, also for "
        "their own vote (the party they sit for now only for an undated one) and "
        "`in_office`, the posts of `government_functions` they held on its date "
        "(`function`, `cabinet_key`, `cabinet`; empty when none: a vote as "
        "demissionary bewindspersoon and Kamerlid), `coalition` and "
        "`coalition_factions` as on the feed (null and `[]` without a coalition vote "
        "and in the Eerste Kamer; `limit` (1-200, default 50) and `offset` page them, "
        "`in_office=true` keeps the votes cast in office alone before the page is cut, "
        "and `next_offset` is the offset of the next page, null after a page that was "
        "not full); the dossiers the member authored documents in (`AUTHORED`), each a "
        "dossier summary plus `roles` (the source's role names), `functions` and "
        "`capacities` (what the member signed as there: `kamerlid`, `bewindspersoon`, "
        "`overig`, see data-model (docs/data-model.md#parliament)) and "
        "`document_count`, paged with `total`; in `/api/nodes/members/{key}` every "
        "`AUTHORED` edge carries `meta.role`, `meta.function` and `meta.capacity` of "
        "that signature; laws the member proposed changes to. `?chamber=EK` lists the "
        "members of the Eerste Kamer (with `party` their faction's abbreviation, "
        "`active` those the last snapshot shows); a member of the Eerste Kamer has "
        "`ek`, in the list and the detail"
    ),
    tags=["members"],
)
def list_members(
    store: Annotated[GraphStore, Depends(get_store)],
    party: Annotated[
        str | None, Query(description="Party abbreviation or name.")
    ] = None,
    active: Annotated[
        bool | None, Query(description="Only members currently seated.")
    ] = None,
    q: Annotated[
        str | None,
        Query(description="A part of the name, in any case, with or without accents."),
    ] = None,
    include_all: Annotated[bool, Query()] = False,
    capacity: Annotated[
        Literal["bewindspersoon"] | None,
        Query(
            description="``bewindspersoon``: only those who held a post in a cabinet."
        ),
    ] = None,
    cabinet: Annotated[
        str | None,
        Query(description="Only those who held a post in this cabinet (key)."),
    ] = None,
    slug: Annotated[
        str | None,
        Query(description="The member of this slug (``rob-jetten``); see ``slug``."),
    ] = None,
    sort: Annotated[
        Literal["name", "family_name"],
        Query(
            description="``name`` (default): by the name they go by. ``family_name``: "
            "by surname, then tussenvoegsel, as the Kamer lists its members (Steur, van "
            "der); those without a surname in the source last."
        ),
    ] = "name",
    limit: MemberListLimit = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
    chamber: ListChamber = "TK",
    active_from: ActiveFrom = None,
    active_to: ActiveTo = None,
) -> list[MemberDTO]:
    if chamber == "EK":
        ek = get_ek_members(
            store,
            party=party,
            active=active,
            q=q,
            sort=sort,
            limit=limit,
            offset=offset,
            active_from=iso_day(active_from),
            active_to=iso_day(active_to),
        )
        return [_as_ek_member(MemberDTO.from_document(d)) for d in ek]
    docs = get_members(
        store,
        party=party,
        active=active,
        q=q,
        include_all=include_all,
        government=capacity == "bewindspersoon",
        cabinet=cabinet,
        slug=slug,
        sort=sort,
        limit=limit,
        offset=offset,
        active_from=iso_day(active_from),
        active_to=iso_day(active_to),
    )
    return [MemberDTO.from_document(d) for d in docs]


@router.get(
    "/{key}",
    response_model=MemberDetailDTO,
    summary="Member detail",
    description=(
        "One member of parliament or minister, with the posts they held in a cabinet "
        "(`government_functions`, from Rijksoverheid)."
    ),
    tags=["members"],
)
def get_member(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> MemberDetailDTO:
    document = require_node(store, COLLECTION_MEMBERS, key, "Member")
    return MemberDetailDTO.from_document(
        document, get_member_committees(store, document["id"])
    )


@router.get(
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
    store: Annotated[GraphStore, Depends(get_store)],
    limit: PageLimit = 50,
    offset: Annotated[
        int, Query(ge=0, le=100_000, description="Skip the newest that many votes.")
    ] = 0,
    in_office: Annotated[
        bool,
        Query(
            description="Only the votes cast while the member held a post of the "
            "government (``in_office`` not empty), before the page is cut."
        ),
    ] = False,
) -> MemberVotesResponse:
    member_id = require_node(store, COLLECTION_MEMBERS, key, "Member")["id"]
    votes = get_member_votes(
        store, member_id, limit=limit, offset=offset, in_office=in_office
    )
    return MemberVotesResponse(
        member_id=member_id,
        count=len(votes),
        votes=[MemberVoteDTO(**v) for v in votes],
        next_offset=offset + limit if len(votes) == limit else None,
    )


@router.get(
    "/{key}/documents",
    response_model=MemberDocumentsResponse,
    summary="Papers a member signed",
    description=(
        "The papers this member signed (``AUTHORED`` into a document; the case of a "
        "paper, signed as well, and a commitment are not listed), the newest first by "
        "the date of the paper, an undated one last, then by the key of the edge; "
        "``total`` counts every one, as the ``AUTHORED`` bucket of documents of "
        "``/api/nodes/members/{key}`` does. Each item is a "
        "neighbour as ``/api/nodes`` gives it with ``props=canvas``, with its edge."
    ),
    tags=["members"],
)
def list_member_documents(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: PageLimit = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MemberDocumentsResponse:
    member_id = require_node(store, COLLECTION_MEMBERS, key, "Member")["id"]
    total, entries = get_signed(store, member_id, limit, offset)
    return MemberDocumentsResponse(
        total=total,
        items=[
            NeighborDTO.from_entry(
                doc=entry.doc,
                edge=entry.edge,
                direction=entry.direction,
                confidence=entry.confidence,
            )
            for entry in entries
        ],
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.get(
    "/{key}/dossiers",
    response_model=ActorDossiersResponse,
    summary="Dossiers a member authored in",
    description=(
        "The dossiers in which this member signed or submitted documents "
        "(``AUTHORED``), newest opened first. Each dossier carries the roles "
        "the member had there, the functions and capacities they signed in "
        "(``kamerlid``, ``bewindspersoon``, ``overig``) and the number of documents. "
        "``sort`` ``opened`` (default) is newest opened first; ``importance`` puts the "
        "dossier with the most documents signed first. ``total`` is the absolute count."
    ),
    tags=["members"],
)
def list_member_dossiers(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: ListLimit = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: ActorDossierSort = "opened",
) -> ActorDossiersResponse:
    member = require_node(store, COLLECTION_MEMBERS, key, "Member")
    return actor_dossiers(store, member["id"], limit, offset, sort)


@router.get(
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
    store: Annotated[GraphStore, Depends(get_store)],
    limit: TopLimit = 10,
) -> TouchedInstrumentsResponse:
    member = require_node(store, COLLECTION_MEMBERS, key, "Member")
    return touched_instruments(store, member["id"], limit)


def _as_ek_member(member: MemberDTO) -> MemberDTO:
    """A member in the list of the Eerste Kamer: ``party`` the abbreviation of its faction
    there, ``active`` whether the last snapshot shows it."""
    if member.ek is None:
        return member
    return member.model_copy(
        update={
            "party": member.ek.abbreviation,
            "active": member.ek.observed_until is None,
        }
    )
