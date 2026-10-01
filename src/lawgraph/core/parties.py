"""The colours of the parties and where their factions sit, from the curated lists.

``data/curated/party_colors.json`` gives each party its house colour, the colours each Kamer
draws it in (``chambers``; PRO in two in the Tweede Kamer) and the other names the sources
give it (``GL-PvdA`` and ``PRO`` for GroenLinks-PvdA, ``CU`` for ChristenUnie);
``data/curated/seating.json`` where each faction sits in the plenary hall, taken over from
the plan of the Tweede Kamer (a drawing, no data). ``lawgraph curated`` keeps both.
"""

from __future__ import annotations

from typing import Any

from lawgraph.core.curated import CHAMBERS, LISTS

_PARTIES = LISTS["party-colors"].entries()

# party name -> its house colour (``#003082``); a faction only a Kamer draws has none
PARTY_COLORS: dict[str, str] = {
    name: v["color"] for name, v in _PARTIES.items() if v.get("color")
}
# another name of a party -> its name in the list
PARTY_ALIASES: dict[str, str] = {
    alias: name for name, v in _PARTIES.items() for alias in v.get("aliases") or []
}
# Kamer -> party name -> the colours that Kamer draws it in, as it draws them
CHAMBER_COLORS: dict[str, dict[str, list[str]]] = {
    chamber: {
        name: colors
        for name, v in _PARTIES.items()
        if (colors := (v.get("chambers") or {}).get(chamber))
    }
    for chamber in CHAMBERS
}
# Kamer -> where its colours were read: {url, what, read_on}
CHAMBER_COLOR_SOURCES: dict[str, dict[str, str]] = LISTS["party-colors"].document()[
    "sources"
]
# faction keys in the order they sit, from the chair's left (the angle of the plan)
SEATING: tuple[str, ...] = tuple(
    key
    for key, _ in sorted(
        LISTS["seating"].entries().items(), key=lambda e: e[1]["angle"]
    )
)
# the plan the seating is taken from: {title, dated, url, page, read_on, method}
SEATING_SOURCE: dict[str, str] = LISTS["seating"].document()["source"]


def _by_label(colors: dict[str, Any]) -> dict[str, Any]:
    """*colors* by every name and alias of a party, in lower case."""
    found = {name.lower(): value for name, value in colors.items()}
    found |= {a.lower(): colors[n] for a, n in PARTY_ALIASES.items() if n in colors}
    return found


def chamber_colors(chamber: str, *names: str | None) -> list[str]:
    """The colours *chamber* draws the first of *names* in that it draws; ``[]`` for none."""
    colors = _by_label(CHAMBER_COLORS.get(chamber) or {})
    for name in names:
        if name and (hit := colors.get(name.lower())):
            return list(hit)
    return []


def party_color(*names: str | None, chamber: str | None = None) -> str | None:
    """The colour of the first of *names* (abbreviation, full name) that is a party or an
    alias of one, without regard to case: the first one *chamber* draws it in, else its
    house colour; ``None`` when none is."""
    if chamber and (drawn := chamber_colors(chamber, *names)):
        return drawn[0]
    colors = _by_label(PARTY_COLORS)
    for name in names:
        if name and (hit := colors.get(name.lower())):
            return str(hit)
    return None
