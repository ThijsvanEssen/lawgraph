"""Parliament-level endpoints — the composition of the Tweede Kamer and the Eerste Kamer."""

from __future__ import annotations

import datetime as dt
from itertools import count
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.ek_source import EkSourceDTO
from lawgraph.api.schemas.parliament import (
    FactionSeatsDTO,
    HallDTO,
    HallPlaceDTO,
    ParliamentSeatsResponse,
    SeatingPlanDTO,
)
from lawgraph.config.constants import Chamber
from lawgraph.config.settings import EK_ATTRIBUTION
from lawgraph.core.coalition import EK_SEATS, TK_SEATS, vacant_on
from lawgraph.core.ek_composition import FACTIONS_PATH, HALL_PATH
from lawgraph.core.ek_pages import MUTATIONS_PATH
from lawgraph.core.official_urls import ek_url
from lawgraph.core.parties import (
    SEATING,
    SEATING_SOURCE,
    chamber_colors,
    party_color,
)
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries import ek_seats
from lawgraph.db.queries.coalition import (
    Coalition,
    coalition_of_day,
    vacancies_between,
)
from lawgraph.db.queries.factions import get_factions, get_seats_on
from lawgraph.db.queries.members import get_ek_members
from lawgraph.db.queries.not_found import NotFound

router = APIRouter()

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
        "\n\n"
        "seated factions with seat counts in the order they sit in the plenary hall, "
        "from the chair's left (`order`), after the seating plan of the Tweede Kamer "
        "(`seating_plan`: `title`, `dated`, `url`, `page`; kept with `lawgraph curated "
        "set seating`, updated at every Presidium decision on the seating; a faction "
        "the plan does not place sits at the right end); `?date=YYYY-MM-DD` gives the "
        "seats the members held that day (complete from the Kamer installed on 30 "
        "November 2006) and per faction its `vacant` seats that day, no member holding "
        "them (with `seats`, the faction's seats as the stretches of "
        "`/api/cabinets/{key}/seats` count them), in the order of today's plan. "
        "`?chamber=EK`: the seats of the Eerste Kamer (`total_seats` 75) as "
        "eerstekamer.nl shows them on the day it was last read (`as_of`, `source`), in "
        "the order of their size, no `seating_plan`; with `date`, the seats of that "
        "day as walked from the Kiesraad's result through the changes the Kamer's "
        "pages tell (`normalize eerstekamer-mutations`; `source.composition_date` the "
        "first day of that stretch, `checked` false when its term did not add up, a "
        "faction of the past with `id` and `key` null; `hall` from `hall_read_on` on; "
        "404 before 2003). Each faction has `colors`, the colours that Kamer draws it "
        "in (two for a faction drawn in stripes, PRO in the Tweede Kamer; empty for "
        "none), and `color`, the first of them or else the party's house colour. Each "
        "faction has `coalition` (of the coalition of the cabinet in office on "
        "`as_of`, named in `cabinet`: `key`, `name`; null when none was), so the hall "
        "can mark coalition and opposition"
    ),
    tags=["parliament"],
)
def get_seats(
    store: Annotated[GraphStore, Depends(get_store)],
    date: Annotated[
        dt.date | None, Query(description="The day, YYYY-MM-DD; today when left out.")
    ] = None,
    chamber: Annotated[
        Chamber,
        Query(
            description="``EK``: the seats of the Eerste Kamer, in the order of their "
            "size (no plan): without ``date`` as eerstekamer.nl shows them on the day it "
            "was last read; with it, those of that day as walked from the Kiesraad's "
            "result through the changes the Kamer's pages tell (404 before 2003), and "
            "``hall`` from the day Wie zit waar was read (``hall_read_on``)."
        ),
    ] = "TK",
) -> ParliamentSeatsResponse:
    if chamber == "EK":
        return (
            _ek_seats(store) if date is None else _ek_seats_on(store, date.isoformat())
        )
    return _tk_seats(store, date)


def _tk_seats(store: GraphStore, date: dt.date | None) -> ParliamentSeatsResponse:
    """The seats of the Tweede Kamer today, or held on *date*, in the order of the hall."""
    vacant: dict[str, int] = {}
    if date is None:
        factions = get_factions(store, active=True)
        seats = {
            doc["key"]: int((doc.get("props") or {}).get("seats") or 0)
            for doc in factions
        }
    else:
        day = date.isoformat()
        seats = get_seats_on(store, day)
        # the seats of a faction no member held that day: with those it holds, its seats
        # as the stretches of a cabinet count them (``/api/cabinets/{key}/seats``)
        vacant = vacant_on(vacancies_between(store, day, day), day)
        factions = [
            doc
            for doc in get_factions(store)
            if doc["key"] in seats or doc["key"] in vacant
        ]
    seated = [
        doc
        for doc in factions
        if seats.get(doc["key"], 0) + vacant.get(doc["key"], 0) > 0
    ]
    as_of = (date or dutch_today()).isoformat()
    coalition = coalition_of_day(store, as_of)
    items = sorted(
        (
            _faction_seats(
                doc,
                "TK",
                (doc.get("props") or {}).get("name"),
                seats.get(doc["key"], 0),
                order,
                coalition,
                vacant=vacant.get(doc["key"], 0),
            )
            for doc, order in zip(seated, _hall_order(seated), strict=True)
        ),
        key=lambda item: item.order,
    )
    return ParliamentSeatsResponse(
        cabinet=coalition.cabinet,
        total_seats=TK_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=as_of,
        factions=items,
        seating_plan=SeatingPlanDTO(
            **{k: SEATING_SOURCE[k] for k in ("title", "dated", "url", "page")}
        ),
        source=None,
        hall=None,
        hall_read_on=None,
        checked=None,
    )


def _hall_order(factions: list[dict[str, Any]]) -> list[int]:
    """The place of each of *factions* in the hall of the Tweede Kamer, from the chair's
    left (``SEATING``); one the plan does not place after every other, in their order."""
    unplaced = count(len(SEATING))
    return [
        _ORDER[d["key"]] if d["key"] in _ORDER else next(unplaced) for d in factions
    ]


def _faction_seats(
    doc: dict[str, Any] | None,
    chamber: str,
    name: str | None,
    seats: int,
    order: int,
    coalition: Coalition,
    *,
    abbreviation: str | None = None,
    vacant: int = 0,
) -> FactionSeatsDTO:
    """A faction in the seats of *chamber*: *doc* its node (None: a faction of the past),
    its colours by *abbreviation* (default that of *doc*) and the name of *doc*, and
    whether it is of the coalition (None when no cabinet was in office)."""
    props = (doc or {}).get("props") or {}
    abbreviation = abbreviation or props.get("abbreviation")
    key = doc["key"] if doc else None
    return FactionSeatsDTO(
        id=doc["id"] if doc else None,
        key=key,
        abbreviation=abbreviation,
        name=name,
        seats=seats,
        vacant=vacant,
        color=party_color(abbreviation, props.get("name"), chamber=chamber),
        colors=chamber_colors(chamber, abbreviation, props.get("name")),
        order=order,
        coalition=coalition.has(key or "", abbreviation) if coalition.cabinet else None,
    )


def _ek_seats(store: GraphStore) -> ParliamentSeatsResponse:
    """The seats of the Eerste Kamer as eerstekamer.nl showed them when last read, by size."""
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
    read_on = _read_on(factions)
    hall = _hall(store)
    as_of = read_on or dutch_today().isoformat()
    coalition = coalition_of_day(store, as_of)
    items = [
        _faction_seats(
            doc,
            "EK",
            doc["props"].get("name"),
            int(doc["props"]["seats"]),
            order,
            coalition,
        )
        for order, doc in enumerate(factions)
    ]
    return ParliamentSeatsResponse(
        chamber="EK",
        cabinet=coalition.cabinet,
        total_seats=EK_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=as_of,
        factions=items,
        seating_plan=None,
        source=EkSourceDTO(
            url=ek_url(FACTIONS_PATH),
            retrieved_on=read_on or None,
            composition_date=read_on or None,
            data_since=min(
                (d for doc in factions if (d := doc["props"].get("data_since"))),
                default=None,
            ),
            attribution=EK_ATTRIBUTION,
        ),
        hall=hall,
        hall_read_on=(read_on or None) if hall else None,
        checked=None,
    )


def _ek_seats_on(store: GraphStore, day: str) -> ParliamentSeatsResponse:
    """The seats of the Eerste Kamer on *day*, from its stretch (``lg_ek_seats``): by size;
    a faction of the past has no key."""
    stretch = ek_seats.stretch_on(store, day)
    if stretch is None:
        raise NotFound("Seats of the Eerste Kamer", day)
    factions = get_factions(store, chamber="EK")
    keys = {
        str((doc.get("props") or {}).get("abbreviation") or "").upper(): doc
        for doc in factions
    }
    # Wie zit waar shows the plan of the day it is read only: a day before it has none
    hall = _hall(store)
    read_on = _read_on(factions) if hall else ""
    coalition = coalition_of_day(store, day)
    ranked = sorted(
        ((name, n) for name, n in (stretch["seats"] or {}).items() if n > 0),
        key=lambda r: (-r[1], r[0]),
    )
    items = []
    for order, (name, n) in enumerate(ranked):
        doc = keys.get(name.upper())
        known = ((doc or {}).get("props") or {}).get("name")
        items.append(
            _faction_seats(
                doc, "EK", known or name, n, order, coalition, abbreviation=name
            )
        )
    kiesraad = (stretch.get("source") or {}).get("kiesraad") or {}
    return ParliamentSeatsResponse(
        chamber="EK",
        cabinet=coalition.cabinet,
        total_seats=EK_SEATS,
        assigned_seats=sum(item.seats for item in items),
        as_of=day,
        factions=items,
        seating_plan=None,
        source=EkSourceDTO(
            url=ek_url(MUTATIONS_PATH),
            retrieved_on=kiesraad.get("read_on"),
            composition_date=stretch["from_date"],
            data_since=None,
            attribution=EK_ATTRIBUTION,
        ),
        hall=hall if read_on and day >= read_on else None,
        hall_read_on=read_on or None,
        checked=bool(stretch["checked"]),
    )


def _read_on(factions: list[dict[str, Any]]) -> str:
    """The day eerstekamer.nl was last read: that of the latest snapshot of its factions."""
    return max(
        ((doc.get("props") or {}).get("retrieved_on") or "" for doc in factions),
        default="",
    )[:10]


# The order of the blocks of the hall of the Eerste Kamer in its plan.
_BLOCKS = {"left": 0, "chair": 1, "right": 2}


def _hall(store: GraphStore) -> HallDTO | None:
    """Who sits where in the hall of the Eerste Kamer, from the seats of its members."""
    places = [
        HallPlaceDTO(
            **ek["seat"],
            faction=ek.get("faction") or "",
            abbreviation=ek.get("abbreviation"),
            member=doc["key"],
            name=ek.get("name"),
        )
        for doc in get_ek_members(store, active=True)
        if (ek := (doc.get("props") or {}).get("ek") or {}).get("seat")
    ]
    if not places:
        return None
    places.sort(key=lambda p: (_BLOCKS[p.block], p.row, p.column))
    return HallDTO(url=ek_url(HALL_PATH), seats=places)
