"""The colours of the parties and where their factions sit, from the curated lists.

``data/curated/party_colors.json`` gives each party its house colour and the other names the
sources give it (``GL-PvdA`` and ``PRO`` for GroenLinks-PvdA, ``CU`` for ChristenUnie);
``data/curated/left_right.json`` the factions left to right as they sit in the chamber. No
official source gives either; ``lawgraph curated`` keeps them.
"""

from __future__ import annotations

from lawgraph.core.curated import LISTS

_PARTIES = LISTS["party-colors"].entries()

# party name -> its house colour (``#003082``)
PARTY_COLORS: dict[str, str] = {name: v["color"] for name, v in _PARTIES.items()}
# another name of a party -> the name it has in ``PARTY_COLORS``
PARTY_ALIASES: dict[str, str] = {
    alias: name for name, v in _PARTIES.items() for alias in v.get("aliases") or []
}
# faction keys, left to right
LEFT_TO_RIGHT: tuple[str, ...] = tuple(LISTS["left-right"].entries())


def party_color(*names: str | None) -> str | None:
    """The colour of the first of *names* (abbreviation, full name) that is a party or an
    alias of one, without regard to case; ``None`` when none is."""
    colors = {name.lower(): color for name, color in PARTY_COLORS.items()}
    colors |= {a.lower(): PARTY_COLORS[n] for a, n in PARTY_ALIASES.items()}
    for name in names:
        if name and (hit := colors.get(name.lower())):
            return hit
    return None
