"""Which factions form the coalition of a cabinet, day by day, and its seats over time.

Pure: no I/O. The coalition on a day is the factions whose party held a post in the cabinet
that day (``meta.posts`` of ``SERVED_IN``, from Rijksoverheid): a party that leaves the
cabinet leaves the coalition the day its last post ends, whatever the fixed list of the
cabinet's parties says. A faction that splits off a coalition party is a faction of its own
that holds no post: opposition (Thijs, 2026-10-09). A post without a faction (``partijloos``)
makes no faction coalition.

The seats of a faction on a day are the members whose membership period covers it
(``faction_memberships``, FractieZetelPersoon): complete from the Kamer installed on 30
November 2006 (``TK_SEATS_FROM``); a cabinet that began before has no seat timeline.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# The first day every seat of the Tweede Kamer is known (FractieZetelPersoon).
TK_SEATS_FROM = "2006-11-30"
# The seats of each Kamer, and the majority of them.
TK_SEATS, EK_SEATS = 150, 75
TK_MAJORITY, EK_MAJORITY = TK_SEATS // 2 + 1, EK_SEATS // 2 + 1


@dataclass(frozen=True)
class Period:
    """Days *start* to *end*, both inclusive; *end* None: still running."""

    start: str
    end: str | None

    def covers(self, day: str) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


def _next_day(day: str) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()


def _period(row: Mapping[str, Any], start_key: str, end_key: str) -> Period | None:
    start = str(row.get(start_key) or "")[:10]
    end = str(row.get(end_key) or "")[:10] or None
    return Period(start, end) if start else None


def coalition_on(posts: Iterable[Mapping[str, Any]], day: str) -> set[str]:
    """The faction keys whose party held a post of the cabinet on *day*."""
    found: set[str] = set()
    for post in posts:
        faction = ((post.get("party") or {}).get("faction")) or None
        period = _period(post, "from_date", "to_date")
        if faction and period and period.covers(day):
            found.add(str(faction))
    return found


def change_days(periods: Iterable[Period], start: str, end: str) -> list[str]:
    """The days within *start*..*end* on which one of *periods* begins or the day after it
    ends; *start* first, each once, in order."""
    days = {start}
    for period in periods:
        for day in (period.start, _next_day(period.end) if period.end else None):
            if day and start < day <= end:
                days.add(day)
    return sorted(days)


def seats_on(memberships: Sequence[Mapping[str, Any]], day: str) -> dict[str, int]:
    """Faction key -> its seats on *day*: the members whose period covers it. *memberships*
    are ``{member, faction_key, from_date, to_date}``; a member counts once per faction."""
    members: dict[str, set[str]] = {}
    for row in memberships:
        period = _period(row, "from_date", "to_date")
        faction = row.get("faction_key")
        if faction and period and period.covers(day):
            members.setdefault(str(faction), set()).add(str(row.get("member")))
    return {faction: len(keys) for faction, keys in members.items()}


def vacant_on(vacancies: Iterable[Mapping[str, Any]], day: str) -> dict[str, int]:
    """Faction key -> its seats held by no member on *day* (``vacancies`` of a faction:
    ``{faction_key, from_date, to_date}``, both inclusive)."""
    found: dict[str, int] = {}
    for row in vacancies:
        period = _period(row, "from_date", "to_date")
        faction = row.get("faction_key")
        if faction and period and period.covers(day):
            found[str(faction)] = found.get(str(faction), 0) + 1
    return found


def seat_timeline(
    posts: Sequence[Mapping[str, Any]],
    memberships: Sequence[Mapping[str, Any]],
    start: str,
    end: str,
    vacancies: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """The seats of the coalition and the opposition from *start* to *end*, one segment per
    stretch in which neither the coalition nor any faction's seats changed:
    ``{from_date, to_date, coalition, opposition, vacant, coalition_vacant, factions: [{key,
    seats, vacant, coalition}]}``, the factions by seats, the coalition first. A faction's
    seats are its members' and its vacant ones (a vacant seat is still its faction's), so
    ``coalition`` and ``opposition`` count their parties' seats; ``vacant`` is every seat no
    member held, of a faction or of none, ``coalition_vacant`` the coalition's: the seats
    held are the Kamer's but the vacant ones. A day on which the coalition or a seat changes
    starts a segment."""
    periods = [
        p
        for row in [*posts, *memberships, *vacancies]
        if (p := _period(row, "from_date", "to_date")) is not None
    ]
    days = change_days(periods, start, end)
    segments: list[dict[str, Any]] = []
    for day in days:
        coalition = coalition_on(posts, day)
        seats = seats_on(memberships, day)
        vacant = vacant_on(vacancies, day)
        for key, n in vacant.items():  # a vacant seat is still its faction's
            seats[key] = seats.get(key, 0) + n
        ranked = sorted(
            ((key, n, key in coalition) for key, n in seats.items() if n > 0),
            key=lambda f: (not f[2], -f[1], f[0]),
        )
        factions = [
            {"key": k, "seats": n, "vacant": vacant.get(k, 0), "coalition": c}
            for k, n, c in ranked
        ]
        # a seat no member and no vacancy of a faction accounts for is vacant too
        unaccounted = max(TK_SEATS - sum(n for _, n, _c in ranked), 0)
        segment = {
            "from_date": day,
            "to_date": end,
            "coalition": sum(n for _, n, c in ranked if c),
            "opposition": sum(n for _, n, c in ranked if not c),
            "vacant": sum(vacant.values()) + unaccounted,
            "coalition_vacant": sum(vacant.get(k, 0) for k, _n, c in ranked if c),
            "factions": factions,
        }
        if segments and segments[-1]["factions"] == factions:
            continue  # nothing changed that day: the stretch goes on
        if segments:
            segments[-1]["to_date"] = (
                dt.date.fromisoformat(day) - dt.timedelta(days=1)
            ).isoformat()
        segments.append(segment)
    return segments


# The choices that count as a vote cast (``VOTED`` ``meta.choice``); any other is none.
VOTE_FOR, VOTE_AGAINST = "Voor", "Tegen"
# The pattern of the coalition on a vote: all its votes on one side, on both sides, or on
# both sides while the side that won holds coalition and opposition seats.
PATTERN_TOGETHER, PATTERN_SPLIT, PATTERN_WISSEL = "together", "split", "wissel"


def vote_pattern(
    votes: Iterable[tuple[str, str, int]], coalition: set[str]
) -> dict[str, Any] | None:
    """What the coalition did on a vote. *votes* are ``(faction key, choice, seats)``: a
    faction vote with its seats that day, or one member of a roll call as one seat of the
    faction they sat in; *coalition* the faction keys of the coalition that day. None when
    no seat of the coalition voted (no cabinet, or it did not take part).

    ``passed``: more seats for than against (a tie is rejected, as the Kamer counts it).
    ``together``: every coalition seat on one side; ``split``: on both. ``wissel``: split,
    and the side with the most coalition seats lost (a wisselmeerderheid: part of the
    coalition with the opposition beat the rest of it). ``carried``: passed with the
    coalition's seats for alone more than half of those cast. ``decisive``: the opposition
    alone would have decided otherwise (a coalition with a majority could always turn a
    vote, which says nothing). ``factions``: each coalition faction that cast a seat,
    ``{key, choice, seats_for, seats_against}``, most seats first, then by key;
    ``choice`` is ``Voor`` or ``Tegen``, null when its seats went both ways (a roll
    call)."""
    own: dict[str, list[int]] = {}
    seats = {
        (True, VOTE_FOR): 0,
        (True, VOTE_AGAINST): 0,
        (False, VOTE_FOR): 0,
        (False, VOTE_AGAINST): 0,
    }
    for faction, choice, n in votes:
        if choice in (VOTE_FOR, VOTE_AGAINST):
            seats[(faction in coalition, choice)] += max(int(n or 0), 0)
            if faction in coalition:
                own.setdefault(faction, [0, 0])[choice == VOTE_AGAINST] += max(
                    int(n or 0), 0
                )
    c_for, c_against = seats[(True, VOTE_FOR)], seats[(True, VOTE_AGAINST)]
    o_for, o_against = seats[(False, VOTE_FOR)], seats[(False, VOTE_AGAINST)]
    if c_for + c_against == 0:
        return None
    passed = c_for + o_for > c_against + o_against
    split = c_for > 0 and c_against > 0
    # the side with the most coalition seats lost (none when they are even)
    wissel = split and (c_for > c_against) != passed and c_for != c_against
    cast = c_for + c_against + o_for + o_against
    # the opposition alone: would it have decided the same?
    decisive = (o_for > o_against) != passed
    return {
        "coalition_for": c_for,
        "coalition_against": c_against,
        "opposition_for": o_for,
        "opposition_against": o_against,
        "passed": passed,
        "pattern": PATTERN_WISSEL
        if wissel
        else PATTERN_SPLIT
        if split
        else PATTERN_TOGETHER,
        "carried": passed and 2 * c_for > cast,
        "decisive": decisive,
        "factions": [
            {
                "key": key,
                "choice": None if f and a else VOTE_FOR if f else VOTE_AGAINST,
                "seats_for": f,
                "seats_against": a,
            }
            for key, (f, a) in sorted(own.items(), key=lambda kv: (-sum(kv[1]), kv[0]))
        ],
    }


# ── what starts a stretch of the Tweede Kamer ─────────────────────────────────

# The Tweede Kamer gives no reason for a change of seats: the kind of an event is derived from
# the periods of the seats (FractieZetelPersoon, FractieZetelVacature) and the posts, by these
# rules (``basis`` ``afgeleid``, no ``words``).
DERIVED = "afgeleid"
# A day on which at least this many seats begin is the installation of a new Kamer.
INSTALLATION_SEATS = 50


def tk_events(
    day: str,
    memberships: Sequence[Mapping[str, Any]],
    vacancies: Sequence[Mapping[str, Any]],
    coalition_before: set[str] | None,
    coalition_now: set[str],
) -> list[dict[str, Any]]:
    """The events that begin a stretch of the Tweede Kamer on *day*, each ``{kind, date,
    words: None, basis: "afgeleid", factions, members}``:

    - ``verkiezing``: at least ``INSTALLATION_SEATS`` seats begin (a new Kamer installed);
    - ``afsplitsing``: a member's seat ends in one faction and begins the next day in a
      faction no seat was held in before; ``overstap`` when it was;
    - ``vacature``: a seat of a faction becomes vacant; ``opvolging``: a seat that a member
      left, or that was vacant, is taken by another;
    - ``coalitie``: the factions of the coalition change (a party joins or leaves).
    """
    before = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    began = [m for m in memberships if m.get("from_date") == day]
    ended = [m for m in memberships if m.get("to_date") == before]
    events: list[dict[str, Any]] = []

    def event(kind: str, factions: list[str], members: list[str]) -> None:
        events.append(
            {"kind": kind, "date": day, "words": None, "basis": DERIVED,
             "factions": sorted(set(factions)), "members": sorted(set(members))}
        )  # fmt: skip

    if len(began) >= INSTALLATION_SEATS:
        event("verkiezing", [str(m["faction_key"]) for m in began], [])
        return events
    held_before = {
        m.get("faction_key") for m in memberships if (m.get("from_date") or "") < day
    }
    moved = {m["member"] for m in began} & {m["member"] for m in ended}
    for member in sorted(moved):
        old = next(m["faction_key"] for m in ended if m["member"] == member)
        new = next(m["faction_key"] for m in began if m["member"] == member)
        if old != new:
            kind = "overstap" if new in held_before else "afsplitsing"
            event(kind, [old, new], [member])
    gone = [m for m in ended if m["member"] not in moved]
    came = [m for m in began if m["member"] not in moved]
    vacant_from = {v["faction_key"] for v in vacancies if v.get("from_date") == day}
    for m in gone:
        if m["faction_key"] in vacant_from:
            event("vacature", [m["faction_key"]], [m["member"]])
    for m in came:
        event("opvolging", [m["faction_key"]], [m["member"]])
    if coalition_before is not None and coalition_before != coalition_now:
        event("coalitie", sorted(coalition_before ^ coalition_now), [])
    return events
