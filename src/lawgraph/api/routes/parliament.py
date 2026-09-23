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
)
from lawgraph.config.constants import PARTY_COLORS
from lawgraph.db import ArangoStore
from lawgraph.db.queries.committees import get_factions

router = APIRouter()

TOTAL_PARLIAMENT_SEATS: int = 150

# Where each party sits, left to right, in the chamber. Keyed by faction node
# key. Parties not listed fall to the right end. Kept by hand: there is no
# machine-readable source for political ideology.
_LEFT_TO_RIGHT: tuple[str, ...] = (
    "sp",
    "groenlinks_pvda",
    "pvdd",
    "volt",
    "denk",
    "50plus",
    "d66",
    "cda",
    "christenunie",
    "lid_keijzer",
    "vvd",
    "sgp",
    "bbb",
    "ja21",
    "fvd",
    "pvv",
    "groep_markuszower",
)
_ORDER = {key: index for index, key in enumerate(_LEFT_TO_RIGHT)}
_COLORS = {name.lower(): color for name, color in PARTY_COLORS.items()}


def _color(abbreviation: str | None, name: str | None) -> str | None:
    for candidate in (abbreviation, name):
        if candidate and (hit := _COLORS.get(candidate.lower())):
            return hit
    return None


@router.get(
    "/seats",
    response_model=ParliamentSeatsResponse,
    summary="Current seat composition of the Tweede Kamer",
    description=(
        "The seated parties with their seat counts, ordered left to right as "
        "they sit in the chamber — enough to render a hemicycle."
    ),
    tags=["parliament"],
)
def get_seats(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ParliamentSeatsResponse:
    items: list[FactionSeatsDTO] = []
    assigned = 0
    unplaced = len(_LEFT_TO_RIGHT)

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
                color=_color(props.get("abbreviation"), props.get("name")),
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
    )


party_router = APIRouter()


@party_router.get(
    "/colors",
    response_model=PartyColorsResponse,
    summary="Party colours",
    description=(
        "Party abbreviation to hex colour, from the parties' own house "
        "styles, for rendering vote chips."
    ),
    tags=["parties"],
)
def get_party_colors() -> PartyColorsResponse:
    return PartyColorsResponse(colors=dict(PARTY_COLORS))
