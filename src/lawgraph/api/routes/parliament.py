"""Parliament-level endpoints — the composition of the Tweede Kamer and the Eerste Kamer."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.committees import EkSourceDTO
from lawgraph.api.schemas.parliament import (
    ChamberColorsDTO,
    ColorSourceDTO,
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
    CHAMBER_COLOR_SOURCES,
    CHAMBER_COLORS,
    PARTY_ALIASES,
    PARTY_COLORS,
    SEATING,
    SEATING_SOURCE,
    chamber_colors,
    party_color,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import ek_seats
from lawgraph.db.queries.coalition import Coalition, coalition_of_day
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
    store: Annotated[GraphStore, Depends(get_store)],
    date: Annotated[
        dt.date | None, Query(description="The day, YYYY-MM-DD; today when left out.")
    ] = None,
    chamber: Annotated[
        Literal["TK", "EK"],
        Query(
            description="``EK``: the seats of the Eerste Kamer, in the order of their "
            "size (no plan): without ``date`` as eerstekamer.nl shows them on the day it "
            "was last read; with it, those of that day as walked from the Kiesraad's "
            "result through the changes the Kamer's pages tell (404 before 2003)."
        ),
    ] = "TK",
) -> ParliamentSeatsResponse:
    if chamber == "EK":
        if date is not None:
            return _ek_seats_on(store, date.isoformat())
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

    as_of = (date or dt.date.today()).isoformat()
    coalition = coalition_of_day(store, as_of)
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
                **_colors("TK", props.get("abbreviation"), props.get("name")),
                order=order,
                coalition=_of_coalition(coalition, key, props.get("abbreviation")),
            )
        )

    items.sort(key=lambda item: item.order)
    return ParliamentSeatsResponse(
        cabinet=coalition.cabinet,
        total_seats=TOTAL_PARLIAMENT_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=as_of,
        factions=items,
        seating_plan=SeatingPlanDTO(
            **{k: SEATING_SOURCE[k] for k in ("title", "dated", "url", "page")}
        ),
        source=None,
        hall=None,
        checked=None,
    )


def _colors(chamber: str, *names: str | None) -> dict[str, Any]:
    """``color`` and ``colors`` of a faction with *names* in *chamber*."""
    return {
        "color": party_color(*names, chamber=chamber),
        "colors": chamber_colors(chamber, *names),
    }


def _of_coalition(
    coalition: Coalition, key: str, abbreviation: str | None
) -> bool | None:
    """Whether the faction is of the coalition; None when no cabinet was in office."""
    return coalition.has(key, abbreviation) if coalition.cabinet else None


def _ek_seats(store: GraphStore) -> ParliamentSeatsResponse:
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
    read_on = max(
        (doc["props"].get("retrieved_on") or "" for doc in factions), default=""
    )
    coalition = coalition_of_day(store, (read_on or dt.date.today().isoformat())[:10])
    items = [
        FactionSeatsDTO(
            id=doc["_id"],
            key=doc["_key"],
            abbreviation=doc["props"].get("abbreviation"),
            name=doc["props"].get("name"),
            seats=int(doc["props"]["seats"]),
            **_colors("EK", doc["props"].get("abbreviation"), doc["props"].get("name")),
            order=order,
            coalition=_of_coalition(
                coalition, doc["_key"], doc["props"].get("abbreviation")
            ),
        )
        for order, doc in enumerate(factions)
    ]
    return ParliamentSeatsResponse(
        chamber="EK",
        cabinet=coalition.cabinet,
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
        checked=None,
    )


def _ek_seats_on(store: GraphStore, day: str) -> ParliamentSeatsResponse:
    """The seats of the Eerste Kamer on *day*, from its stretch (``lg_ek_seats``): by size;
    a faction of the past has no key."""
    stretch = ek_seats.stretch_on(store, day)
    if stretch is None:
        raise HTTPException(
            status_code=404, detail=f"No seats of the Eerste Kamer are known on {day}."
        )
    keys = {
        str((doc.get("props") or {}).get("abbreviation") or "").upper(): doc
        for doc in get_factions(store, chamber="EK")
    }
    coalition = coalition_of_day(store, day)
    ranked = sorted(
        ((name, n) for name, n in (stretch["seats"] or {}).items() if n > 0),
        key=lambda r: (-r[1], r[0]),
    )
    items = []
    for order, (name, n) in enumerate(ranked):
        doc = keys.get(name.upper())
        props = (doc or {}).get("props") or {}
        items.append(
            FactionSeatsDTO(
                id=doc["_id"] if doc else None,
                key=doc["_key"] if doc else None,
                abbreviation=name,
                name=props.get("name") or name,
                seats=n,
                **_colors("EK", name, props.get("name")),
                order=order,
                coalition=_of_coalition(coalition, doc["_key"] if doc else "", name),
            )
        )
    kiesraad = (stretch.get("source") or {}).get("kiesraad") or {}
    return ParliamentSeatsResponse(
        chamber="EK",
        cabinet=coalition.cabinet,
        total_seats=TOTAL_SENATE_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=day,
        factions=items,
        seating_plan=None,
        source=EkSourceDTO(
            url=EERSTEKAMER_SITE.rstrip("/") + "/personele_mutaties",
            retrieved_on=kiesraad.get("read_on"),
            composition_date=stretch["from_date"],
            data_since=None,
            attribution=EK_ATTRIBUTION,
        ),
        hall=None,
        checked=bool(stretch["checked"]),
    )


# The order of the blocks of the hall of the Eerste Kamer in its plan.
_BLOCKS = {"left": 0, "chair": 1, "right": 2}


def _hall(store: GraphStore) -> HallDTO | None:
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
        "`aliases` another name of a party -> its name in `colors`; `chambers` the "
        "colours each Kamer draws its factions in, with where they were read. Kept by hand "
        "(`lawgraph curated set party-colors`): no source gives colours as data."
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
        chambers={
            chamber: ChamberColorsDTO(
                colors={
                    **colors,
                    **{
                        alias: colors[name]
                        for alias, name in PARTY_ALIASES.items()
                        if name in colors
                    },
                },
                source=ColorSourceDTO(**CHAMBER_COLOR_SOURCES[chamber]),
            )
            for chamber, colors in CHAMBER_COLORS.items()
        },
    )
