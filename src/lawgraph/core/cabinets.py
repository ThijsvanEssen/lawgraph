"""Dutch cabinets: one name, a key, the period, the faction of a party.

Sources name a cabinet in several ways (``Kabinet-Balkenende II (2003-2006)``, ``Kabinet
Balkenende I (2002-2003)``, ``kabinet-Rutte III``); ``cabinet_name`` writes all of them as
``kabinet-<name>``, and ``cabinet_key`` makes the node key from it (``balkenende_ii``,
``den_uyl``). ``wikidata_period`` reads the period of a cabinet Wikidata knows before 1945,
often only by a year.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any


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


def _plain(text: str | None) -> str:
    plain = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in plain if not unicodedata.combining(c)).lower().strip()


def _capitals(name: str | None) -> str:
    """``nsc`` of ``Nieuw Sociaal Contract``, ``cu`` of ``ChristenUnie``."""
    return "".join(c for c in name or "" if c.isupper()).lower()


def faction_of(party: dict[str, Any], factions: Iterable[dict[str, Any]]) -> str | None:
    """The key of the faction that bears the name or abbreviation of *party*, or ``None``
    (a party from before the Tweede Kamer data begins). *factions* are ``{key, name,
    abbreviation, aliases}``. A faction the Tweede Kamer gives no abbreviation of
    (``Nieuw Sociaal Contract``) is known by the capitals of its name (``NSC``), when they
    name one faction only."""
    factions = list(factions)
    names = {_plain(party.get("name")), _plain(party.get("short"))} - {""}
    for faction in factions:
        own = {
            _plain(faction.get("name")),
            _plain(faction.get("abbreviation")),
            *(_plain(a) for a in faction.get("aliases") or []),
        }
        if names & own:
            return str(faction["key"])
    by_capitals = [
        f
        for f in factions
        if len(_capitals(f.get("name"))) > 1 and _capitals(f.get("name")) in names
    ]
    return str(by_capitals[0]["key"]) if len(by_capitals) == 1 else None


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


# Wikidata's wikibase:timePrecision, as a cabinet node names it.
PRECISION_NAMES = {11: "day", 10: "month", 9: "year"}


def wikidata_period(record: dict[str, Any]) -> dict[str, Any]:
    """``{from_date, from_date_precision, to_date, to_date_precision}`` of a Wikidata
    cabinet as Wikidata gives it: a date it lacks stays ``None``, a year stays a year
    (dated the first of January). Nothing is taken from the cabinets around it: Wikidata
    lacks some, so the next start is not this end."""
    period: dict[str, Any] = {}
    for field in ("from_date", "to_date"):
        day = record.get(field)
        period[field] = day
        period[f"{field}_precision"] = (
            PRECISION_NAMES.get(record.get(f"{field}_precision") or 0) if day else None
        )
    return period
