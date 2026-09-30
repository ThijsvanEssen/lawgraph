"""Every Dutch cabinet since 1945, from its Rijksoverheid page.

Rijksoverheid has a page for every cabinet since 1945 (``core.rijksoverheid``): the cabinet
starts on the day of its beëdiging and ends when the next one starts; its posts
(``core.cabinet_posts``), phases (``core.cabinet_phases``) and parties come from it. The
cabinets before 1945 are not in the graph: no official source describes them.

``build_cabinets`` does all of it without a database; the pipeline adds the members.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from lawgraph.core.cabinet_phases import (
    EVENT_SWORN_IN,
    cabinet_events,
    cabinet_phases,
    demissionary_from,
    formation_start,
    page_events,
)
from lawgraph.core.cabinet_posts import cabinet_posts
from lawgraph.core.cabinets import cabinet_key, cabinet_name

SOURCE_NAME_RIJKSOVERHEID = "rijksoverheid"
NO_PARTY = "partijloos"

# party text -> ``{short, faction}``
PartyOf = Callable[[str | None], dict[str, Any] | None]


def _sworn_in(page: dict[str, Any]) -> str | None:
    days = [
        f["date"] for f in page["facts"] if f["label"].lower().startswith("beëdiging")
    ]
    return days[0] if days else page["intro_from"]


def _party(post: dict[str, Any], party_of: PartyOf) -> dict[str, Any] | None:
    return party_of(post["party"]) if post["party"] else None


def _parties(posts: list[dict[str, Any]], start: str) -> list[dict[str, Any]]:
    """The parties of the bewindspersonen sworn in on the first day, the party with the
    most of them first."""
    counts: Counter[tuple[str | None, str | None]] = Counter()
    for post in posts:
        party = post["party"]
        if post["from_date"] == start and party and party["short"] != NO_PARTY:
            counts[(party["short"], party["faction"])] += 1
    return [
        {"short": short, "faction": faction}
        for (short, faction), _ in sorted(
            counts.items(), key=lambda c: (-c[1], c[0][0] or "")
        )
    ]


def rijksoverheid_cabinets(
    pages: Iterable[dict[str, Any]], party_of: PartyOf
) -> list[dict[str, Any]]:
    """The cabinets of the Rijksoverheid pages, oldest first. *pages* are ``{slug, url,
    read_on, page}``, ``page`` a ``parse_page`` result."""
    cabinets = []
    for record in pages:
        page = record["page"]
        start = _sworn_in(page)
        if not start:
            continue
        name = cabinet_name(page["name"]) or record["slug"]
        cabinets.append(
            {
                "key": cabinet_key(name) or record["slug"],
                "name": name,
                "from_date": start,
                "to_date": None,
                "intro_from": page["intro_from"],
                "intro_to": page["intro_to"],
                "source": {
                    "name": SOURCE_NAME_RIJKSOVERHEID,
                    "url": record["url"],
                    "read_on": record["read_on"],
                },
                "page": page,
            }
        )
    cabinets.sort(key=lambda c: c["from_date"])
    for i, cabinet in enumerate(cabinets):
        after = cabinets[i + 1] if i + 1 < len(cabinets) else None
        cabinet["to_date"] = after["from_date"] if after else cabinet["intro_to"]
    events = [
        event
        for cabinet in cabinets
        for event in page_events(cabinet["page"], cabinet["source"])
    ]
    terms = cabinet_events(events, cabinets)
    for cabinet in cabinets:
        own = [e for e in events if e["source"] is cabinet["source"]]
        sworn = next((e for e in own if e["event"] == EVENT_SWORN_IN), None) or {
            "label": cabinet["page"]["intro"][:200],
            "source": cabinet["source"],
        }
        cabinet["phases"] = cabinet_phases(
            cabinet,
            sworn,
            formation_start(own, cabinet["from_date"]),
            terms[cabinet["key"]],
        )
        cabinet["demissionary_from"] = demissionary_from(cabinet["phases"])
        posts = cabinet_posts(cabinet["page"], cabinet)
        for post in posts:
            post["party"] = _party(post, party_of)
            post["cabinet_key"] = cabinet["key"]
            post["cabinet"] = cabinet["name"]
            post["source"] = cabinet["source"]
        cabinet["posts"] = posts
        cabinet["parties"] = _parties(posts, cabinet["from_date"])
    return cabinets


def build_cabinets(
    pages: Iterable[dict[str, Any]], party_of: PartyOf
) -> list[dict[str, Any]]:
    """Every cabinet, oldest first, each with ``previous`` the one before it. A key two
    cabinets would share gets the start year of the later one."""
    cabinets = rijksoverheid_cabinets(pages, party_of)
    taken: set[str] = set()
    for cabinet in cabinets:
        if cabinet["key"] in taken:
            cabinet["key"] = f"{cabinet['key']}_{(cabinet['from_date'] or '')[:4]}"
        taken.add(cabinet["key"])
    for cabinet, previous in zip(cabinets, [None, *cabinets], strict=False):
        cabinet["previous"] = previous["key"] if previous else None
        for post in cabinet["posts"]:
            post["cabinet_key"] = cabinet["key"]
    return cabinets
