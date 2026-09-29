"""Parliament-level endpoints — the composition of the Tweede Kamer."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.parliament import (
    FactionSeatsDTO,
    ParliamentSeatsResponse,
    PartyColorsResponse,
    SeatingPlanDTO,
)
from lawgraph.core.parties import (
    PARTY_ALIASES,
    PARTY_COLORS,
    SEATING,
    SEATING_SOURCE,
    party_color,
)
from lawgraph.db import ArangoStore
from lawgraph.db.queries.committees import get_factions, get_seats_on

router = APIRouter()

TOTAL_PARLIAMENT_SEATS: int = 150

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
) -> ParliamentSeatsResponse:
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
    )


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
