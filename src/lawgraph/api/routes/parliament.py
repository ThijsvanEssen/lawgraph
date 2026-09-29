"""Parliament-level endpoints — the composition of the Tweede Kamer."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends

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
from lawgraph.db.queries.committees import get_factions

router = APIRouter()

TOTAL_PARLIAMENT_SEATS: int = 150

# Where each faction sits, from the chair's left (``data/curated/seating.json``, after the plan
# of the Tweede Kamer); a faction the plan does not place sits at the right end.
_ORDER = {key: index for index, key in enumerate(SEATING)}


@router.get(
    "/seats",
    response_model=ParliamentSeatsResponse,
    summary="Current seat composition of the Tweede Kamer",
    description=(
        "The seated parties with their seat counts, in the order they sit in the "
        "plenary hall from the chair's left (the plan of the Tweede Kamer, kept with "
        "`lawgraph curated set seating`; a faction it does not place sits at the right "
        "end) — enough to render a hemicycle. `seating_plan` names the plan."
    ),
    tags=["parliament"],
)
def get_seats(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ParliamentSeatsResponse:
    items: list[FactionSeatsDTO] = []
    assigned = 0
    unplaced = len(SEATING)

    for doc in get_factions(store, active=True):
        props = doc.get("props") or {}
        seats = int(props.get("seats") or 0)
        if seats <= 0:
            continue
        key = doc["_key"]
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
                seats=seats,
                color=party_color(props.get("abbreviation"), props.get("name")),
                order=order,
            )
        )
        assigned += seats

    items.sort(key=lambda item: item.order)
    return ParliamentSeatsResponse(
        total_seats=TOTAL_PARLIAMENT_SEATS,
        assigned_seats=assigned,
        as_of=dt.date.today().isoformat(),
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
