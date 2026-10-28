"""Whether a member has a role in the sources (pure): a seat in a faction of the Tweede Kamer
(``faction_memberships``), a post in a cabinet (``government_functions``), a seat in the
Eerste Kamer (``ek``, its composition) or a period in one of its factions
(``ek_faction_memberships``, their page). A member without one is a person of the Tweede
Kamer's records only (``Persoon``) whose seat the data does not hold: their page is not
indexed, the sitemap leaves them out, and search lists them after the members with one.

``db.queries.member_role.has_role`` is the same test in SQL; a test keeps the two equal.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# the props that are a role when they hold a list with something in it
ROLE_LISTS = (
    "faction_memberships",
    "government_functions",
    "ek_faction_memberships",
)


def has_role(props: Mapping[str, Any]) -> bool:
    """Whether *props* (of a member) hold a seat or a post."""
    return any(
        isinstance(props.get(field), list) and len(props[field]) > 0
        for field in ROLE_LISTS
    ) or isinstance(props.get("ek"), dict)


def _spells(props: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    return [s for s in props.get(field) or [] if isinstance(s, Mapping)]


def _day(spell: Mapping[str, Any], field: str) -> str:
    value = spell.get(field)
    return value if isinstance(value, str) else ""


def _lasts(spell: Mapping[str, Any], today: str) -> bool:
    """Whether a spell (``from_date``, ``to_date``) lasts on *today*."""
    start, end = _day(spell, "from_date"), _day(spell, "to_date")
    return (not start or start <= today) and (not end or end >= today)


def _last_day(spells: list[Mapping[str, Any]]) -> str:
    """The day a list of spells last was (the far future where one still lasts)."""
    return max((_day(s, "to_date") or "9999" for s in spells), default="")


def is_minister(props: Mapping[str, Any], today: str) -> bool:
    """Whether a member is a bewindspersoon rather than a Kamerlid by the current role, as
    the site has it (``rubrieken.ts``, ``isMinister``): a post in a cabinet that lasts
    *today*; else not with a seat in a fractie that lasts; else the role that ended last.
    Without a post: a Kamerlid."""
    posts = _spells(props, "government_functions")
    if not posts:
        return False
    if any(_lasts(p, today) for p in posts):
        return True
    seats = _spells(props, "faction_memberships")
    if any(_lasts(m, today) for m in seats):
        return False
    return not seats or _last_day(posts) >= _last_day(seats)
