"""The seats of the factions of the Eerste Kamer through a term, day by day.

A term begins with the seats each list of the Kiesraad's result won (``start_seats``), by the
names a faction is known by (``known_factions``); every change ``core.ek_change_patterns``
reads is walked from there (``walk``): a stretch per day the seats changed, and what did not
add up."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from lawgraph.core.coalition import EK_SEATS
from lawgraph.core.ek_change_patterns import Change, member_key
from lawgraph.core.kiesraad import list_names
from lawgraph.core.time import day_before, shift_day


def initials(name: str) -> str:
    """The initials of a faction's name, upper case: of its words and of the capitals
    inside one (``GroenLinks`` GL, ``ChristenUnie`` CU, ``Partij van de Arbeid`` PVDA)."""
    parts = re.findall(r"[A-Z][a-z]*|\b[a-z]+", re.sub(r"[^\w\s]", " ", name))
    return "".join(p[0] for p in parts).upper()


def faction_key(name: str) -> str:
    """The name of a faction as it is matched: ``BBB-fractie``, ``de BBB`` and ``BBB`` alike,
    without dots, in upper case."""
    name = re.sub(r"^(de|het)\s+", "", name.strip(), flags=re.I)
    name = re.sub(r"[-\s]?fractie$", "", name, flags=re.I)
    return name.replace(".", "").strip().upper()


# Within so many days of a term's first day, a member sworn in with no seat open was elected.
LATE_DAYS = 60
# Of the changes of one day: the factions merged and renamed first, then the members who go,
# then who change faction, then who come.
_ORDER = {"samenvoeging": 0, "hernoeming": 1, "vertrek": 2, "overstap": 3, "afsplitsing": 3,
          "beëdiging": 4}  # fmt: skip


@dataclass
class Stretch:
    """The seats of the factions from a day until the day before the next stretch."""

    from_date: str
    to_date: str | None
    seats: dict[str, int]
    events: list[Change] = field(default_factory=list)


@dataclass
class Walk:
    """The stretches of a term and what did not add up: ``mismatches`` (the changes whose
    faction is not known, a faction short of seats, more seats than the Kamer has);
    ``checked`` when there are none."""

    stretches: list[Stretch]
    mismatches: list[str]

    @property
    def checked(self) -> bool:
        return not self.mismatches


class _Seats:
    """The seats of the factions while a term is walked: per faction (by ``faction_key``) its
    name and seats, the faction each member was last seen in, the members gone."""

    def __init__(self, seats: dict[str, int], late: str = "") -> None:
        self.late = late
        self.names: dict[str, str] = {}
        self.count: dict[str, int] = {}
        self.member_of: dict[str, str] = {}
        self.gone: set[str] = set()
        self.vacant: dict[str, int] = {}
        self.mismatches: list[str] = []
        for name, n in seats.items():
            self._add(name, n)

    def _add(self, name: str, n: int) -> None:
        key = self._resolve(name)
        self.names.setdefault(key, name)
        self.count[key] = self.count.get(key, 0) + n

    def _resolve(self, name: str) -> str:
        """The key a faction's *name* counts under: its own, else that of a faction already
        counted whose name is its initials or whose initials it is (``GroenLinks`` and
        ``GL``, ``ChristenUnie`` and ``CU``)."""
        key = faction_key(name)
        if key in self.count:
            return key
        mine = initials(name)
        for other in self.count:
            if other == mine or initials(self.names[other]) == key:
                return other
        return key

    def add(self, name: str | None, n: int, change: Change) -> bool:
        if not name:
            self.mismatches.append(
                f"{change.date}: {change.kind} of {change.member}: no faction"
            )
            return False
        key = self._resolve(name)
        self._add(name, n)
        if self.count[key] < 0:
            self.mismatches.append(
                f"{change.date}: {self.names[key]} below 0 ({change.words})"
            )
        return True

    def apply(self, change: Change) -> None:
        member = member_key(change.member)
        if change.kind == "samenvoeging":
            total = sum(self.count.pop(faction_key(s), 0) for s in change.sources)
            self.add(change.to, total, change)
        elif change.kind == "hernoeming":
            key = faction_key(change.source or "")
            if key in self.count and change.to:
                self.names[faction_key(change.to)] = change.to
                self.count[faction_key(change.to)] = self.count.pop(key)
        elif change.kind == "vertrek":
            if member not in self.gone:
                self.gone.add(member)
                faction = change.source or self.member_of.get(member)
                if self.add(faction, -1, change):
                    key = self._resolve(faction or "")
                    self.vacant[key] = self.vacant.get(key, 0) + 1
        elif change.kind in ("overstap", "afsplitsing"):
            if self.add(change.source or self.member_of.get(member), -1, change):
                self.add(change.to, 1, change)
            self.member_of[member] = faction_key(change.to or "")
        elif change.kind == "beëdiging":
            self._sworn(member, change)
        if sum(self.count.values()) > EK_SEATS:
            self.mismatches.append(
                f"{change.date}: more than {EK_SEATS} seats ({change.words})"
            )

    def _sworn(self, member: str, change: Change) -> None:
        """A member sworn in fills a seat their faction left open; one sworn in within the
        term's first weeks with no seat open was elected and sworn in late (the Kiesraad's
        result counts them already)."""
        self.gone.discard(member)
        if not change.to:
            # the faction of the one they succeed, else their own (a stand-in kept on)
            faction = self.member_of.get(
                member_key(change.succeeds)
            ) or self.member_of.get(member)
            change = replace(change, to=self.names.get(faction or ""))
        key = self._resolve(change.to or "")
        if change.to and not self.vacant.get(key) and change.date <= self.late:
            self.member_of[member] = key
            return
        if self.add(change.to, 1, change):
            self.vacant[key] = self.vacant.get(key, 0) - 1
            self.member_of[member] = key

    def now(self) -> dict[str, int]:
        return {k: v for k, v in self.count.items() if v}


def walk(start: str, seats: dict[str, int], changes: list[Change], until: str) -> Walk:
    """The seats of a term from its first day (*start*, *seats* per faction by name) through
    *changes* to *until*. A member's faction is the one the change names, else the one the
    walk last saw them in; a member already gone is gone once."""
    state = _Seats(seats, shift_day(start, LATE_DAYS))
    stretches = [Stretch(start, None, state.now())]
    kept = sorted(
        (c for c in changes if start <= c.date <= until),
        key=lambda c: (c.date, _ORDER.get(c.kind, 9)),
    )
    for change in kept:
        before = state.now()
        state.apply(change)
        current = state.now()
        if current == before:
            continue
        last = stretches[-1]
        if last.from_date == change.date:
            last.seats = current
            last.events.append(change)
        else:
            last.to_date = day_before(change.date)
            stretches.append(Stretch(change.date, None, current, [change]))
    for stretch in stretches:
        stretch.seats = {state.names[k]: v for k, v in stretch.seats.items() if v}
    return Walk(stretches, state.mismatches)


def _faction_of_list(names: set[str], factions: dict[str, set[str]]) -> str | None:
    """The faction one of whose names (``factions``: name to its names) is one of *names*
    (a list's, ``kiesraad.list_names``)."""
    return next((f for f, known in factions.items() if names & known), None)


def _short_name(listed: str) -> str:
    """The name a list of no known faction goes by: its abbreviation in brackets, else its
    name (``Partij voor de Dieren (PvdD)`` is ``PvdD``)."""
    short = re.search(r"\(([^)]+)\)\s*$", listed)
    return short.group(1) if short else listed


def start_seats(
    lists: dict[str, int], factions: dict[str, set[str]]
) -> tuple[dict[str, int], list[str]]:
    """The seats of a term's first day by faction name: each list of the Kiesraad's result
    (by name, its seats) to the faction one of whose names (``factions``: name to the names
    it is matched by, upper case: abbreviation, full name) is one of the list's
    (``kiesraad.list_names``); a list that matches none keeps its own short name and is
    reported."""
    seats: dict[str, int] = {}
    unmatched = []
    for name, n in lists.items():
        match = _faction_of_list(list_names(name), factions)
        if match is None:
            match = _short_name(name)
            unmatched.append(name)
        seats[match] = seats.get(match, 0) + n
    return seats, unmatched


def known_factions(
    today: dict[str, set[str]],
    lists: Iterable[str],
    changes: list[Change],
    spelled: Iterable[str] = (),
) -> dict[str, set[str]]:
    """Every faction by name and the names it is matched by (upper case): today's (*today*);
    each list of the Kiesraad's (*lists*) as the faction of today it is one of, else as a
    faction of its own by its short name; each with the names in full the texts give
    (*spelled*, ``spelled_out``); then each faction a change names that is none of those."""
    found = {name: set(known) for name, known in today.items()}
    for listed in lists:
        names = list_names(listed)
        match = _faction_of_list(names, found)
        if match is None:
            match = _short_name(listed)
        found[match] = found.get(match, set()) | names
    for listed in spelled:
        names = list_names(listed)
        if (match := _faction_of_list(names, found)) is not None:
            found[match] |= names
    _named_as_told(found, set(today), changes)
    every = {alias for known in found.values() for alias in known}
    for change in changes:
        for name in (change.source, change.to, *change.sources):
            if (
                name
                and name.upper() not in every
                and name.replace(".", "").upper() not in every
            ):
                found.setdefault(name, aliases(name))
    return found


def _named_as_told(
    found: dict[str, set[str]], keep: set[str], changes: list[Change]
) -> None:
    """Each faction not of today by the name the changes call it most (``PvdA``, not the
    Kiesraad's ``P.v.d.A.``)."""
    told = Counter(n for c in changes for n in (c.source, c.to, *c.sources) if n)
    for name in [n for n in found if n not in keep]:
        names = [n for n in told if n.upper() in found[name]]
        best = max(names, key=lambda n: told[n], default=name)
        if best != name and best not in found:
            found[best] = found.pop(name)


def canonical(changes: list[Change], factions: dict[str, set[str]]) -> list[Change]:
    """The changes with each faction by the name of the faction it is one of the names of
    (``factions``: name to its names, upper case): ``Partij voor de Vrijheid`` is ``PVV``."""
    by_alias = {alias: name for name, known in factions.items() for alias in known}

    def one(name: str | None) -> str | None:
        if not name:
            return name
        return by_alias.get(
            name.upper(), by_alias.get(name.replace(".", "").upper(), name)
        )

    return [
        replace(
            c,
            source=one(c.source),
            to=one(c.to),
            sources=tuple(one(n) or n for n in c.sources),
        )
        for c in changes
    ]


def aliases(abbreviation: str, path: str = "") -> set[str]:
    """The names a faction is matched by: its abbreviation, without dots, and the full name
    its page's path spells (``/fractie/forum_voor_democratie``)."""
    found = {abbreviation.upper(), abbreviation.replace(".", "").upper()}
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    if slug:
        found.add(slug.replace("_", " ").upper())
    return found
