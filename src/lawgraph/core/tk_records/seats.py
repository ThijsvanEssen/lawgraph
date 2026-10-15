"""FractieZetelPersoon and FractieZetelVacature: who held a seat of a faction, and when
no one did."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.core.time import day_before, iso_date, shift_day
from lawgraph.core.tk_records._payload import (
    Payload,
    dicts,
)


def seat_holding(payload: Payload) -> tuple[str, str, dict[str, Any]] | None:
    """``(Persoon_Id, Fractie_Id, period)`` for a FractieZetelPersoon record; ``None``
    without a person or a faction."""
    person_id = str(payload.get("Persoon_Id") or "")
    seat = next(dicts(payload.get("FractieZetel")), {})
    faction_id = str(seat.get("Fractie_Id") or "")
    if not person_id or not faction_id:
        return None
    return (
        person_id,
        faction_id,
        {
            "from_date": iso_date(payload.get("Van")),
            "to_date": iso_date(payload.get("TotEnMet")),
            "role": payload.get("Functie") or None,
        },
    )


def seat_vacancy(payload: Payload) -> tuple[str, dict[str, Any]] | None:
    """``(Fractie_Id, period)`` for a FractieZetelVacature record: a seat of the faction no
    member held, ``from_date`` to ``to_date`` inclusive (None: still vacant). The record's
    ``TotEnMet`` is the day the successor takes the seat (whose own seat begins that day),
    so the last vacant day is the one before. None without a faction or a start, or
    when it ends before it begins (the source holds such records)."""
    seat = next(dicts(payload.get("FractieZetel")), {})
    faction_id = str(seat.get("Fractie_Id") or "")
    start, until = iso_date(payload.get("Van")), iso_date(payload.get("TotEnMet"))
    if not faction_id or not start:
        return None
    end = day_before(until) if until else None
    if end is not None and end < start:
        return None
    return faction_id, {"from_date": start, "to_date": end}


def vacancy_seat(payload: Payload) -> str | None:
    """The FractieZetel a FractieZetelVacature record is a vacancy of."""
    seat = next(dicts(payload.get("FractieZetel")), {})
    return str(seat.get("Id") or payload.get("FractieZetel_Id") or "") or None


def holding_of_seat(payload: Payload) -> tuple[str, dict[str, Any]] | None:
    """``(FractieZetel_Id, period)`` of a FractieZetelPersoon record: the days a person held
    the seat, both inclusive; None without a seat or a start."""
    seat = next(dicts(payload.get("FractieZetel")), {})
    seat_id = str(payload.get("FractieZetel_Id") or seat.get("Id") or "")
    start = iso_date(payload.get("Van"))
    if not seat_id or not start:
        return None
    return seat_id, {"from_date": start, "to_date": iso_date(payload.get("TotEnMet"))}


def vacant_periods(
    vacancy: dict[str, Any], held: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The days of *vacancy* (``seat_vacancy``) its seat was held by no one: a seat is held
    or vacant, never both, and a vacancy ends at the latest the day before the seat is taken
    again (*held*: the periods of the seat's holdings, ``holding_of_seat``). The source
    holds vacancies that begin on the predecessor's last day, and some it never closed; and
    a vacancy of a seat no one ever held (Fractie Bontes, 2017-02-13), which is no seat of
    the Kamer: none."""
    start, end = str(vacancy["from_date"]), vacancy.get("to_date")
    periods = sorted(
        (str(h["from_date"]), h.get("to_date")) for h in held if h.get("from_date")
    )
    if not periods:
        return []
    for begins, _ends in periods:
        if begins > start and (end is None or begins <= end):
            end = day_before(begins)
            break
    free: list[dict[str, Any]] = []
    day = start
    for begins, ends in periods:
        if end is not None and begins > end:
            break
        if ends is not None and ends < day:
            continue
        if begins > day:
            free.append({"from_date": day, "to_date": day_before(begins)})
        if ends is None:
            return free
        day = shift_day(ends, 1)
    if end is None or day <= end:
        free.append({"from_date": day, "to_date": end})
    return free


def seat_changed_on(payload: Payload) -> str | None:
    """The day the FractieZetel of a FractieZetelPersoon record last changed (its
    ``GewijzigdOp``): when a seat goes to another faction, the seating of the plenary hall
    may change with it."""
    seat = next(dicts(payload.get("FractieZetel")), {})
    return iso_date(seat.get("GewijzigdOp"))
