"""A seat over the names of its ministry, and which seat a person acted from on a day.

A seat (``core.cabinet_posts``) carries the name its ministry had: ``ienm/minister`` and
``ienw/minister`` are one office. ``family`` follows the renames of the ministry
(``CONTINUES``, one name followed by one). A merger is no rename: two names ending on one day
for one successor (``venw`` and ``vrom`` into ``ienm``) stay offices of their own, which
``merged_from`` and ``merged_into`` name. Lanes of an unnamed seat (``bz/staatssecretaris#2``,
a numbering by date, no office of its own) are one seat: ``base_seat``.

A seat without a ministry (``staatssecretaris/herstel-en-toeslagen``) has no family, and a
portfolio spelled otherwise on a later page is another seat: both are gaps of the source.

``seat_acted_from`` attributes something a person did, as ``core.signatories`` does: the
post of the kind of the function they did it in, held that day. The function's wording is not
read for the seat: a minister of Asiel en Migratie makes commitments the Tweede Kamer files
under Justitie en Veiligheid. Only when they held two seats of that kind that day does the
ministry of the thing decide; if it does not, it belongs to neither.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from lawgraph.core.cabinet_posts import SEAT_DEPUTY
from lawgraph.core.ministries import MINISTRIES, MINISTRY_BY_KEY
from lawgraph.core.signatories import held_on, post_kind


def base_seat(seat: str) -> str:
    """The seat without its lane: ``bz/staatssecretaris`` of ``bz/staatssecretaris#2``."""
    return seat.partition("#")[0]


def _successions() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """The ``(ministry, successor)`` pairs that are renames, and those that are mergers."""
    ending = [
        (ministry.key, period.to_date, period.successor)
        for ministry in MINISTRIES
        for period in ministry.periods
        if period.successor in MINISTRY_BY_KEY
    ]
    sharing = Counter((to_date, successor) for _, to_date, successor in ending)
    renames: set[tuple[str, str]] = set()
    mergers: set[tuple[str, str]] = set()
    for key, to_date, successor in ending:
        kind = mergers if sharing[(to_date, successor)] > 1 else renames
        kind.add((key, str(successor)))
    return renames, mergers


_RENAMES, _MERGERS = _successions()


def _renamed(ministry: str) -> set[str]:
    """Every name *ministry* went by, itself among them."""
    names = {ministry}
    grown = True
    while grown:
        reached = {
            other
            for pair in _RENAMES
            if names.intersection(pair)
            for other in pair
            if other not in names
        }
        names |= reached
        grown = bool(reached)
    return names


def _split(seat: str) -> tuple[str, str] | None:
    """``(ministry, the rest)`` of a seat; ``None`` without a ministry, as for the one shared
    seat of the viceminister-president."""
    ministry, slash, rest = base_seat(seat).partition("/")
    return (ministry, rest) if slash and ministry in MINISTRY_BY_KEY else None


def family(seat: str) -> list[str]:
    """The seat under every name of its ministry, sorted; itself alone without a ministry."""
    parts = _split(seat)
    if parts is None:
        return [base_seat(seat)]
    return sorted(f"{name}/{parts[1]}" for name in _renamed(parts[0]))


def ministries_of(seat: str) -> list[str]:
    """The ministry of a seat under every name it went by, sorted; none without one."""
    parts = _split(seat)
    return sorted(_renamed(parts[0])) if parts else []


def _merged(seat: str, *, into: bool) -> list[str]:
    parts = _split(seat)
    if parts is None:
        return []
    names = _renamed(parts[0])
    return sorted(
        f"{source if into else target}/{parts[1]}"
        for source, target in _MERGERS
        if (target if into else source) in names
        and (source if into else target) not in names
    )


def merged_from(seat: str) -> list[str]:
    """The seats of the ministries that merged into this one: other offices."""
    return _merged(seat, into=True)


def merged_into(seat: str) -> list[str]:
    """The seat of the ministry this one merged into: another office."""
    return _merged(seat, into=False)


def seat_acted_from(
    posts: Iterable[dict[str, Any]],
    *,
    day: str | None,
    function: str | None,
    ministry: str | None,
) -> str | None:
    """The seat (the first of its ``family``) of *posts*, one person's, that something done
    on *day* in *function* under *ministry* belongs to; ``None`` when it fits none or several."""
    if not day:
        return None
    kind = post_kind(function)
    held = [
        post
        for post in posts
        if post.get("seat")
        and post["seat"] != SEAT_DEPUTY
        and post_kind(post.get("function")) == kind
        and held_on(post, day)
    ]
    seats = {family(post["seat"])[0] for post in held}
    if len(seats) > 1:
        seats = {
            family(post["seat"])[0]
            for post in held
            if ministry and post.get("ministry") == ministry
        }
    return seats.pop() if len(seats) == 1 else None


def is_of_kind(seat: str, function: str | None) -> bool:
    """Whether *function* is of the kind (minister, state secretary) of *seat*."""
    return post_kind(seat) == post_kind(function)
