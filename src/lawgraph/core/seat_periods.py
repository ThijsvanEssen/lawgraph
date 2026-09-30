"""The periods of seats in a faction (FractieZetelPersoon), read so they hold together.

A period is ``{"from_date", "to_date", "role"}``: ``to_date`` is the last day the seat was held
(``TotEnMet``: up to and including), ``None`` while it is held. Periods that follow each other
touch, they do not overlap: one ends the day before the next starts.

The Kamer's dates hold together almost everywhere; where they do not, the Kamer's own later
dates say how (nothing here comes from a name or a guess):

- an end before the start (Henk Kamp, VVD, 2006-11-30 to 2003-02-22) is no end: the seat ends
  the day before the person's next seat starts; without a later seat there is no end to read
  and the seat is left out (open, it would seat the person today);
- a fractievoorzitter still chairing after the next one started (Van Ojik until 2015-05-19,
  Klaver from 2015-05-12) chairs until the day before, and holds the rest of that seat as
  a member;
- a faction is active while its seats are held: its record may start or end a day off them
  (GroenLinks-PvdA ends 2026-06-10, its seats 2026-06-09; PRO starts 2026-06-09, its seats
  2026-06-10). The seats date a faction from the Kamer installed on 30 November 2006; before
  it the Kamer keeps the seats of only some members, and the Fractie record's dates stand.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

Period = dict[str, Any]
Holding = tuple[str, str, Period]  # (person, faction, period)

# FractieZetelPersoon.Functie of the one who chairs a faction; the others are ``Lid``.
CHAIR = "Fractievoorzitter"
MEMBER = "Lid"

# From the Kamer installed on this day FractieZetelPersoon holds every seat (148-150 on any
# day); before it, the seats of the members who also sat later (92 on 2002-05-23).
SEATS_COMPLETE_FROM = "2006-11-30"


def day_before(day: str) -> str:
    return (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()


def mend_reversed_ends(holdings: list[Holding]) -> list[Holding]:
    """``(person, faction, period)`` holdings, an end the Kamer typed before the start read
    from the person's next seat (see the module)."""
    starts: dict[str, list[str]] = {}
    for person, _, period in holdings:
        if period.get("from_date"):
            starts.setdefault(person, []).append(period["from_date"])
    mended: list[Holding] = []
    for person, faction, period in holdings:
        start, end = period.get("from_date"), period.get("to_date")
        if start and end and end < start:
            later = min((s for s in starts[person] if s > start), default=None)
            if later is None:
                continue
            period = {**period, "to_date": day_before(later)}
        mended.append((person, faction, period))
    return mended


def split_overlapping_chairs(holdings: list[Holding]) -> list[Holding]:
    """``(person, faction, period)`` holdings with one fractievoorzitter per faction at a time:
    a chair whose period runs into the next chair's chairs until the day before, and holds
    the rest of that seat as a member (``Lid``)."""
    chairs: dict[str, list[tuple[str, Period]]] = {}
    for person, faction, period in holdings:
        if period.get("role") == CHAIR and period.get("from_date"):
            chairs.setdefault(faction, []).append((person, period))
    handovers: dict[
        int, str
    ] = {}  # id of a chair period -> the day the next chair starts
    for held in chairs.values():
        held.sort(key=lambda item: item[1]["from_date"])
        for (person, period), (successor, following) in zip(
            held, held[1:], strict=False
        ):
            start, end = period["from_date"], period.get("to_date")
            takes_over = following["from_date"]
            if (
                person != successor
                and start < takes_over
                and (end or "9") >= takes_over
            ):
                handovers[id(period)] = takes_over

    result: list[Holding] = []
    for person, faction, period in holdings:
        takes_over = handovers.get(id(period))
        if takes_over is None:
            result.append((person, faction, period))
            continue
        result.append((person, faction, {**period, "to_date": day_before(takes_over)}))
        result.append(
            (person, faction, {**period, "from_date": takes_over, "role": MEMBER})
        )
    return result


def seated_bounds(
    active_from: str | None,
    active_until: str | None,
    seats: Iterable[Period],
) -> tuple[str | None, str | None]:
    """A faction's ``(active_from, active_until)`` from its record's, bounded by its seats
    where they date it (see the module): from the first seat when the record starts on or
    after ``SEATS_COMPLETE_FROM``, until the last when the record has ended and so have its
    seats. A seat whose end lies before its start dates only its start."""
    held = [p for p in seats if p.get("from_date")]
    if not held:
        return active_from, active_until
    if active_from and active_from >= SEATS_COMPLETE_FROM:
        active_from = min(p["from_date"] for p in held)
    ends = [p["to_date"] for p in held if (p.get("to_date") or "") >= p["from_date"]]
    ended = all(p.get("to_date") for p in held)
    if active_until and ended and ends and max(ends) >= SEATS_COMPLETE_FROM:
        active_until = max(ends)
    return active_from, active_until
