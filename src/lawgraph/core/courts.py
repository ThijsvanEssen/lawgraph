"""The courts an ECLI names: their tier, kind, official name and days (``data/courts.json``).

The court part of an ECLI (``HR``, ``GHAMS``, ``TGZRAMS``) is the ``Afkorting`` of a court in
the Instanties value list of the Rechtspraak; ``core.court_sources`` makes the table from it.
The courts it does not hold are curated (``data/curated/courts_outside.json``): the EHRM's
own code, and under code ``XX`` the courts outside the Netherlands, which the name the
metadata gives (``dc:creator``) tells apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lawgraph.core.court_sources import (
    TIER_ANDERE,
    TIER_BUITENLAND,
    TIER_CBB,
    TIER_CENTRALE_RAAD,
    TIER_EHRM,
    TIER_GERECHTSHOF,
    TIER_HOGE_RAAD,
    TIER_HVJ_EU,
    TIER_KANTONGERECHT,
    TIER_KONINKRIJK,
    TIER_KROON,
    TIER_PARKET,
    TIER_RAAD_VAN_STATE,
    TIER_RECHTBANK,
    TIER_TUCHTCOLLEGE,
)

CODE_OTHER = "XX"


@dataclass(frozen=True)
class Court:
    code: str
    name: str
    tier: str
    court_kind: str
    type: str | None = None  # the ``Type`` of the value list; None for a curated court
    from_date: str | None = None
    until: str | None = None
    court: str | None = None  # code XX: the name the metadata gives


DATA = Path(__file__).resolve().parents[1] / "data" / "courts.json"
OUTSIDE = (
    Path(__file__).resolve().parents[1] / "data" / "curated" / "courts_outside.json"
)


def load_courts(path: Path) -> tuple[Court, ...]:
    """The courts of a court file, in its order."""
    return tuple(
        Court(
            code=c["code"],
            name=c["name"],
            tier=c["tier"],
            court_kind=c["court_kind"],
            type=c.get("type"),
            from_date=c.get("from"),
            until=c.get("until"),
            court=c.get("court"),
        )
        for c in json.loads(path.read_text(encoding="utf-8"))["courts"]
    )


# The courts of the value list, then the curated ones.
COURTS: tuple[Court, ...] = load_courts(DATA) + load_courts(OUTSIDE)
COURT_BY_CODE: dict[str, Court] = {c.code: c for c in COURTS if c.court is None}
# Code XX: the court by the name its judgments give.
OTHER_COURT_BY_NAME: dict[str, Court] = {c.court: c for c in COURTS if c.court}

# In the order lists show them: the highest courts, the parket, the courts of first
# instance and appeal, the disciplinary tribunals, the other colleges, the Caribbean part,
# then the courts outside the Netherlands, the EHRM last.
TIERS: tuple[str, ...] = (
    TIER_HOGE_RAAD,
    TIER_RAAD_VAN_STATE,
    TIER_CENTRALE_RAAD,
    TIER_CBB,
    TIER_PARKET,
    TIER_GERECHTSHOF,
    TIER_RECHTBANK,
    TIER_KANTONGERECHT,
    TIER_TUCHTCOLLEGE,
    TIER_ANDERE,
    TIER_KONINKRIJK,
    TIER_KROON,
    TIER_BUITENLAND,
    TIER_HVJ_EU,
    TIER_EHRM,
)
# Every court_kind, grouped by tier in the order of ``TIERS``, within a tier as the value
# list first names them.
COURT_KINDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        c.court_kind
        for c in sorted(
            COURTS,
            key=lambda c: TIERS.index(c.tier) if c.tier in TIERS else len(TIERS),
        )
    )
)


def court_of(court_code: str | None, court: str | None = None) -> Court | None:
    """The court of an ECLI code; for code ``XX`` the one *court* (the name the metadata
    gives) names, else the foreign court in general. ``None`` for no code, or one the table
    does not know: never a catch-all."""
    if not court_code:
        return None
    if court_code == CODE_OTHER and (court or "").strip() in OTHER_COURT_BY_NAME:
        return OTHER_COURT_BY_NAME[(court or "").strip()]
    return COURT_BY_CODE.get(court_code)
