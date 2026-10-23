"""Which faction took over another: the faction whose seats all passed to a new one.

Read from the seats of the Tweede Kamer alone (``seat_periods``: who held a seat in which
faction, from and up to and including which day). A faction A that has ended has the
successor B when

- the holders of A on its last day who sit in the Kamer the day after (A's last day or the
  next) all sit in B, one faction, and at least one does;
- B had no seat before that day: a faction that is already there is joined, not continued;
- B has at least as many holders on its first day as A had on its last, so no seat of A
  went elsewhere (the holders who left the Kamer that day had their seat filled in B).

Where the seats do not pass that way (a faction that split, dissolved, or lost a member to
another one) there is no successor, and none is filled in. Two factions that merge into
one are both predecessors of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from lawgraph.core.time import shift_day


@dataclass(frozen=True)
class Holding:
    """A person's seat in a faction, ``to_date`` the last day (None while held)."""

    person: str
    faction: str
    from_date: str
    to_date: str | None


@dataclass(frozen=True)
class Succession:
    predecessor: str
    successor: str
    effective_date: str
    """The first day of the successor's seats that A's holders took."""
    seats: int
    """How many holders of A's last day sit in B."""


def successions(holdings: list[Holding]) -> list[Succession]:
    """The successions among *holdings*, by predecessor."""
    by_faction: dict[str, list[Holding]] = {}
    by_person: dict[str, list[Holding]] = {}
    for holding in holdings:
        by_faction.setdefault(holding.faction, []).append(holding)
        by_person.setdefault(holding.person, []).append(holding)
    found: list[Succession] = []
    for faction in sorted(by_faction):
        seats = by_faction[faction]
        if any(h.to_date is None for h in seats):
            continue  # still has seats
        last = max(h.to_date for h in seats if h.to_date)
        succession = _succession(faction, last, seats, by_faction, by_person)
        if succession is not None:
            found.append(succession)
    return found


def _succession(
    faction: str,
    last: str,
    seats: list[Holding],
    by_faction: dict[str, list[Holding]],
    by_person: dict[str, list[Holding]],
) -> Succession | None:
    holders = {h.person for h in seats if h.to_date == last}
    next_day = shift_day(last, 1)
    destinations: dict[str, set[str]] = {}
    for person in holders:
        for h in by_person[person]:
            if h.faction != faction and _holds(h, next_day):
                destinations.setdefault(h.faction, set()).add(person)
    if len(destinations) != 1:
        return None  # nobody sits on, or the seats went to more than one faction
    ((successor, movers),) = destinations.items()
    successor_seats = by_faction[successor]
    first = min(h.from_date for h in successor_seats)
    if first < last:
        return None  # the successor existed before: it is joined, not continued
    on_first = {h.person for h in successor_seats if _holds(h, first)}
    if len(on_first) < len(holders):
        return None  # a seat of the faction is not in the successor
    return Succession(faction, successor, first, len(movers))


def _holds(holding: Holding, day: str) -> bool:
    return holding.from_date <= day and (
        holding.to_date is None or day <= holding.to_date
    )
