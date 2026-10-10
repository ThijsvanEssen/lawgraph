"""The result of an election of the Eerste Kamer as the Kiesraad publishes it: the page of the
election in its databank (``verkiezingsuitslagen.nl/verkiezingen/detail/EK<yyyymmdd>``), whose
data is a JSON document in the page (``<textarea id="UitslagData">``). Of it: the day of the
election and the seats each list won, by the name the Kiesraad gives the list."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

DATABANK = "https://www.verkiezingsuitslagen.nl/verkiezingen/detail/{code}"
# The elections of the Eerste Kamer whose results start a term of the seats per day: those
# from which the seats of the cabinets are known (the Tweede Kamer's from 30 November 2006).
EK_ELECTIONS = (
    "EK20030526",
    "EK20070529",
    "EK20110523",
    "EK20150526",
    "EK20190527",
    "EK20230530",
)

_DATA = re.compile(r'<textarea id="UitslagData"[^>]*>(.*?)</textarea>', re.S)
# A list named with its abbreviation after it: "Partij van de Arbeid (P.v.d.A.)".
_IN_BRACKETS = re.compile(r"\(([^)]+)\)\s*$")


@dataclass(frozen=True)
class ElectionResult:
    """The seats of an election: its databank code, its day (ISO) and per list its seats."""

    code: str
    date: str
    seats: dict[str, int]


def _with(value: Any, key: str) -> Iterator[dict[str, Any]]:
    """Every object in *value* (nested) that has *key*."""
    if isinstance(value, dict):
        if key in value:
            yield value
        for item in value.values():
            yield from _with(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _with(item, key)


def parse_ek_result(page: str) -> ElectionResult | None:
    """The result on a databank page of an election; None for a page without its data."""
    found = _DATA.search(page)
    if not found:
        return None
    data = json.loads(html.unescape(found.group(1)))
    code = next((str(d["Code"]) for d in _with(data, "Code") if d.get("Code")), "")
    day = next((str(d["DateStemming"]) for d in _with(data, "DateStemming")), "")
    country = next(
        (d for d in _with(data, "Partij") if d.get("Naam") == "Nederland"), None
    )
    if not day or country is None:
        return None
    seats = {
        str(p["Naam"]): int(p["AantalZetels"])
        for p in country.get("Partij") or []
        if p.get("Naam")
        and str(p.get("AantalZetels") or "").isdigit()
        and int(p["AantalZetels"]) > 0
    }
    return ElectionResult(
        code=code,
        date=dt.datetime.strptime(day, "%d-%m-%Y").date().isoformat(),
        seats=seats,
    )


def list_names(name: str) -> set[str]:
    """The names a list may be matched to a faction by, upper case: its own name and the
    abbreviation in brackets after it, with and without its dots ("P.v.d.A." and "PVDA")."""
    names = {name.strip().upper()}
    if found := _IN_BRACKETS.search(name):
        short = found.group(1).strip().upper()
        names |= {short, short.replace(".", "")}
        names.add(_IN_BRACKETS.sub("", name).strip().upper())
    names.discard("")
    return names
