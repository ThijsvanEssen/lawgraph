"""Dutch cabinets as Wikidata records them: one name, a key, the prime minister, the parties.

Wikidata names a cabinet in several ways (``Kabinet-Balkenende II (2003-2006)``, ``Kabinet
Balkenende I (2002-2003)``, ``kabinet-Rutte III``); ``cabinet_name`` writes all of them as
``kabinet-<name>``, and ``cabinet_key`` makes the node key from it (``balkenende_ii``,
``den_uyl``).

The parties of a cabinet are the parties its members belonged to when their post began
(``cabinet_parties``): Wikidata records no coalition, but it records the party of every
person (``member of political party``, with dates where it knows them). A membership without
dates counts when the party existed on that day. An independent is no party, and neither is
a party only one member of the cabinet belonged to. The result follows Wikidata: a person
whose old party it records without dates can still bring that party in.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Any

from lawgraph.core.ministries import POST_PRIME_MINISTER, classify_function

# The Wikidata item "independent politician": a person without a party.
INDEPENDENT = "Q327591"
# The members a party needs in a cabinet to be one of its parties.
MIN_PARTY_MEMBERS = 2


def cabinet_name(label: str | None) -> str | None:
    """``kabinet-Balkenende II`` of ``Kabinet-Balkenende II (2003-2006)``."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", (label or "").strip())
    name = re.sub(r"^kabinet[\s-]+", "", name, flags=re.IGNORECASE).strip()
    return f"kabinet-{name}" if name else None


def cabinet_key(name: str | None) -> str | None:
    """``balkenende_ii`` of ``kabinet-Balkenende II``; ``roell`` of ``kabinet-Röell``."""
    plain = unicodedata.normalize("NFKD", (name or "").removeprefix("kabinet-"))
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return "_".join(re.findall(r"[a-z0-9]+", plain)) or None


def _within(day: str | None, start: str | None, end: str | None) -> bool:
    if not day:
        return not start and not end
    return (not start or start <= day) and (not end or day <= end)


def party_on(person: dict[str, Any], day: str | None) -> list[dict[str, Any]]:
    """The parties *person* belonged to on *day*: a membership whose dates hold the day,
    or, without dates, of a party that existed then."""
    parties = []
    for party in person.get("parties") or []:
        if party.get("id") == INDEPENDENT:
            continue
        dated = party.get("from_date") or party.get("to_date")
        if dated:
            held = _within(day, party.get("from_date"), party.get("to_date"))
        else:
            held = _within(day, party.get("founded"), party.get("dissolved"))
        if held:
            parties.append(party)
    return parties


def cabinet_parties(
    cabinet_id: str, people: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The parties of the members of the cabinet *cabinet_id* when their post in it
    began, the party with the most members first: ``{id, name, short}``.

    A member with one party on that day counts for it. A member with several (a membership
    without dates of a party they left, beside the one they are in) counts only for those
    of them another member counts for, and for none when that leaves nothing to choose.
    A party only one member counts for is left out: a minister from outside the coalition
    (Van Rijn, a PvdA member, in Rutte III) brings no party into it."""
    candidates: list[dict[str, dict[str, Any]]] = []
    for person in people:
        found: dict[str, dict[str, Any]] = {}
        for post in person.get("posts") or []:
            if post.get("cabinet_id") == cabinet_id:
                for party in party_on(person, post.get("from_date")):
                    found[party["id"]] = party
        if found:
            candidates.append(found)
    sure = {next(iter(found)) for found in candidates if len(found) == 1}
    counts: Counter[str] = Counter()
    parties: dict[str, dict[str, Any]] = {}
    for found in candidates:
        chosen = list(found) if len(found) == 1 else [p for p in found if p in sure]
        for party_id in chosen:
            counts[party_id] += 1
            party = found[party_id]
            parties[party_id] = {
                "id": party_id,
                "name": party.get("name"),
                "short": party.get("short"),
            }
    return [
        parties[party_id]
        for party_id, count in sorted(counts.items(), key=lambda c: (-c[1], c[0]))
        if count >= MIN_PARTY_MEMBERS
    ]


def prime_minister(
    cabinet: dict[str, Any], people: Iterable[dict[str, Any]]
) -> str | None:
    """The Q-id of the prime minister of *cabinet*: who held the post of minister-president
    in it first, else its head of government (P6)."""
    held = sorted(
        (post.get("from_date") or "", person["id"])
        for person in people
        for post in person.get("posts") or []
        if post.get("cabinet_id") == cabinet["id"]
        and classify_function(post.get("function"))[0] == POST_PRIME_MINISTER
    )
    if held:
        return held[0][1]
    heads = cabinet.get("heads") or []
    return heads[0] if heads else None


def _plain(text: str | None) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip()


def faction_of(party: dict[str, Any], factions: Iterable[dict[str, Any]]) -> str | None:
    """The key of the faction that bears the name or abbreviation of *party*, or ``None``
    (a party from before the Tweede Kamer data begins). *factions* are ``{key, name,
    abbreviation, aliases}``."""
    names = {_plain(party.get("name")), _plain(party.get("short"))} - {""}
    for faction in factions:
        own = {
            _plain(faction.get("name")),
            _plain(faction.get("abbreviation")),
            *(_plain(a) for a in faction.get("aliases") or []),
        }
        if names & own:
            return str(faction["key"])
    return None


def cabinet_on(day: str | None, cabinets: Iterable[dict[str, Any]]) -> str | None:
    """The key of the cabinet in office on *day*; on the day one cabinet hands over to the
    next, the next. *cabinets* are ``{key, from_date, to_date}``."""
    if not day:
        return None
    held = [
        (c["from_date"], c["key"])
        for c in cabinets
        if c.get("from_date")
        and c["from_date"] <= day
        and (not c.get("to_date") or day <= c["to_date"])
    ]
    return max(held)[1] if held else None
