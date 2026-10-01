"""Parliament-level endpoints — the composition of the Tweede Kamer and the Eerste Kamer."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.committees import EkSourceDTO
from lawgraph.api.schemas.parliament import (
    FactionSeatsDTO,
    HallDTO,
    HallPlaceDTO,
    ParliamentSeatsResponse,
    PartyColorsResponse,
    SeatingPlanDTO,
)
from lawgraph.config.settings import EERSTEKAMER_SITE, EK_ATTRIBUTION
from lawgraph.core.eerstekamer_composition import FACTIONS_PATH, HALL_PATH
from lawgraph.core.parties import (
    PARTY_ALIASES,
    PARTY_COLORS,
    SEATING,
    SEATING_SOURCE,
    party_color,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries.committees import get_ek_members, get_factions, get_seats_on

router = APIRouter()

TOTAL_PARLIAMENT_SEATS: int = 150
TOTAL_SENATE_SEATS: int = 75

# Where each faction sits, from the chair's left (``data/curated/seating.json``, after the plan
# of the Tweede Kamer); a faction the plan does not place sits at the right end.
_ORDER = {key: index for index, key in enumerate(SEATING)}


@router.get(
    "/seats",
    response_model=ParliamentSeatsResponse,
    summary="Seat composition of the Tweede Kamer",
    description=(
        "The seated parties with their seat counts, in the order they sit in the "
        "plenary hall from the chair's left (the plan of the Tweede Kamer, kept with "
        "`lawgraph curated set seating`; a faction it does not place sits at the right "
        "end) — enough to render a hemicycle. `seating_plan` names the plan. With `date`, "
        "the seats on that day: those the members held (FractieZetelPersoon, every seat "
        "from the Kamer installed on 30 November 2006; before it only the seats of members "
        "who also sat later), in the order of today's plan."
    ),
    tags=["parliament"],
)
def get_seats(
    store: Annotated[ArangoStore, Depends(get_store)],
    date: Annotated[
        dt.date | None, Query(description="The day, YYYY-MM-DD; today when left out.")
    ] = None,
    chamber: Annotated[
        Literal["TK", "EK"],
        Query(
            description="``EK``: the seats of the Eerste Kamer as eerstekamer.nl shows "
            "them on the day it was last read, in the order of their size (no plan); "
            "without ``date``."
        ),
    ] = "TK",
) -> ParliamentSeatsResponse:
    if chamber == "EK":
        if date is not None:
            raise HTTPException(
                status_code=422, detail="The Eerste Kamer has no seats per day."
            )
        return _ek_seats(store)
    if date is None:
        factions = get_factions(store, active=True)
        seats = {
            doc["_key"]: int((doc.get("props") or {}).get("seats") or 0)
            for doc in factions
        }
    else:
        seats = get_seats_on(store, date.isoformat())
        factions = [doc for doc in get_factions(store) if doc["_key"] in seats]

    items: list[FactionSeatsDTO] = []
    unplaced = len(SEATING)
    for doc in factions:
        props = doc.get("props") or {}
        key = doc["_key"]
        if seats[key] <= 0:
            continue
        if key in _ORDER:
            order = _ORDER[key]
        else:
            order = unplaced
            unplaced += 1
        items.append(
            FactionSeatsDTO(
                id=doc["_id"],
                key=key,
                abbreviation=props.get("abbreviation"),
                name=props.get("name"),
                seats=seats[key],
                color=party_color(props.get("abbreviation"), props.get("name")),
                order=order,
            )
        )

    items.sort(key=lambda item: item.order)
    return ParliamentSeatsResponse(
        total_seats=TOTAL_PARLIAMENT_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=(date or dt.date.today()).isoformat(),
        factions=items,
        seating_plan=SeatingPlanDTO(
            **{k: SEATING_SOURCE[k] for k in ("title", "dated", "url", "page")}
        ),
        source=None,
        hall=None,
    )


def _ek_seats(store: ArangoStore) -> ParliamentSeatsResponse:
    factions = [
        doc
        for doc in get_factions(store, active=True, chamber="EK")
        if int((doc.get("props") or {}).get("seats") or 0) > 0
    ]
    factions.sort(
        key=lambda doc: (
            -int(doc["props"]["seats"]),
            doc["props"].get("abbreviation") or "",
        )
    )
    items = [
        FactionSeatsDTO(
            id=doc["_id"],
            key=doc["_key"],
            abbreviation=doc["props"].get("abbreviation"),
            name=doc["props"].get("name"),
            seats=int(doc["props"]["seats"]),
            color=party_color(
                doc["props"].get("abbreviation"), doc["props"].get("name")
            ),
            order=order,
        )
        for order, doc in enumerate(factions)
    ]
    read_on = max(
        (doc["props"].get("retrieved_on") or "" for doc in factions), default=""
    )
    return ParliamentSeatsResponse(
        chamber="EK",
        total_seats=TOTAL_SENATE_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=read_on or dt.date.today().isoformat(),
        factions=items,
        seating_plan=None,
        source=EkSourceDTO(
            url=EERSTEKAMER_SITE.rstrip("/") + FACTIONS_PATH,
            retrieved_on=read_on or None,
            composition_date=read_on or None,
            data_since=min(
                (d for doc in factions if (d := doc["props"].get("data_since"))),
                default=None,
            ),
            attribution=EK_ATTRIBUTION,
        ),
        hall=_hall(store),
    )


# The order of the blocks of the hall of the Eerste Kamer in its plan.
_BLOCKS = {"left": 0, "chair": 1, "right": 2}


def _hall(store: ArangoStore) -> HallDTO | None:
    """Who sits where in the hall of the Eerste Kamer, from the seats of its members."""
    places = [
        HallPlaceDTO(
            **ek["seat"],
            faction=ek.get("faction") or "",
            abbreviation=ek.get("abbreviation"),
            member=doc["_key"],
            name=ek.get("name"),
        )
        for doc in get_ek_members(store, active=True, limit=1000)
        if (ek := (doc.get("props") or {}).get("ek") or {}).get("seat")
    ]
    if not places:
        return None
    places.sort(key=lambda p: (_BLOCKS[p.block], p.row, p.column))
    return HallDTO(url=EERSTEKAMER_SITE.rstrip("/") + HALL_PATH, seats=places)


party_router = APIRouter()


@party_router.get(
    "/colors",
    response_model=PartyColorsResponse,
    summary="Party colours",
    description=(
        "Party to hex colour, from the parties' own house styles, for rendering vote "
        "chips: `colors` by every name and alias (matched without regard to case), "
        "`aliases` another name of a party -> its name in `colors`. Kept by hand "
        "(`lawgraph curated set party-colors`): no official source gives them."
    ),
    tags=["parties"],
)
def get_party_colors() -> PartyColorsResponse:
    return PartyColorsResponse(
        colors={
            **PARTY_COLORS,
            **{alias: PARTY_COLORS[name] for alias, name in PARTY_ALIASES.items()},
        },
        aliases=dict(PARTY_ALIASES),
    )
