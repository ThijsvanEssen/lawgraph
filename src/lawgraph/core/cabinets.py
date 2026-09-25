"""Dutch cabinets: one name, a key, the period, the faction of a party.

Sources name a cabinet in several ways (``Kabinet-Balkenende II (2003-2006)``, ``Kabinet
Balkenende I (2002-2003)``, ``kabinet-Rutte III``); ``cabinet_name`` writes all of them as
``kabinet-<name>``, and ``cabinet_key`` makes the node key from it (``balkenende_ii``,
``den_uyl``). ``complete_periods`` completes the periods of the cabinets Wikidata knows
before 1945, often only by a year.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

# wikibase:timePrecision of a date known to the day.
PRECISION_DAY = 11


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


# Wikidata's wikibase:timePrecision, as a cabinet node names it.
PRECISION_NAMES = {11: "day", 10: "month", 9: "year"}


def _precise(precision: int | None) -> bool:
    return (precision or 0) >= PRECISION_DAY


def _same_year(a: str | None, b: str | None) -> bool:
    return bool(a and b and a[:4] == b[:4])


def _meet(end: dict[str, Any], start: dict[str, Any]) -> None:
    """Let the period *end* of one cabinet and *start* of the next meet: an end that is
    missing is the next start; a date known only to the year becomes the other's day when
    that falls in the same year (a year between them means a cabinet Wikidata lacks)."""
    if start["from_date"] and (
        not end["to_date"]
        or (
            not _precise(end["to_date_precision"])
            and _precise(start["from_date_precision"])
            and _same_year(end["to_date"], start["from_date"])
        )
    ):
        end["to_date"] = start["from_date"]
        end["to_date_precision"] = start["from_date_precision"]
    if (
        not _precise(start["from_date_precision"])
        and _precise(end["to_date_precision"])
        and _same_year(start["from_date"], end["to_date"])
    ):
        start["from_date"] = end["to_date"]
        start["from_date_precision"] = end["to_date_precision"]


def complete_periods(cabinets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Q-id -> ``{from_date, from_date_precision, to_date, to_date_precision, previous}``
    of every cabinet (records of ``WikidataClient.cabinets``), completed where Wikidata
    leaves them open. Wikidata knows the old cabinets (before 1945) only by a year and
    often without an end or a predecessor; a cabinet follows the one before it in time:

    - ``previous`` is the cabinet Wikidata names (P155), else the one that started before it;
    - a cabinet without an end ended when the next one started, and an end known only to
      the year is the day the next one started in that year;
    - a start known only to the year is the day the one before ended in that year.

    Only the last cabinet (the one in office) can stay without an end. The precision is
    ``day``, ``month`` or ``year``."""
    ordered = sorted(cabinets, key=lambda c: (c.get("from_date") or "", c["id"]))
    known = {c["id"] for c in ordered}
    periods: dict[str, dict[str, Any]] = {}
    for i, cabinet in enumerate(ordered):
        named = [q for q in cabinet.get("previous") or [] if q in known]
        periods[cabinet["id"]] = {
            "from_date": cabinet.get("from_date"),
            "from_date_precision": cabinet.get("from_date_precision"),
            "to_date": cabinet.get("to_date"),
            "to_date_precision": cabinet.get("to_date_precision"),
            "previous": named[0] if named else (ordered[i - 1]["id"] if i else None),
        }
    for before, after in zip(ordered, ordered[1:], strict=False):
        _meet(periods[before["id"]], periods[after["id"]])
    for period in periods.values():
        for field in ("from_date_precision", "to_date_precision"):
            period[field] = (
                PRECISION_NAMES.get(period[field] or 0)
                if period[field.removesuffix("_precision")]
                else None
            )
    return periods
