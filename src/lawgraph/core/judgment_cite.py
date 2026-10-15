"""A judgment as a lawyer cites it (pure): the court in its usual short form, the day in full,
then the ECLI. ``HR 20 december 2019``, ``Rb. Den Haag 6 juli 2026``, ``Conclusie A-G
Hartlief 8 mei 2020``. The API gives it on every judgment (``cite``), so the app, the tab and
the server HTML cite one judgment alike."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lawgraph.core.courts import CODE_ECHR, court_of
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.ecli import country_code, court_code

_FIXED = {
    "HR": "HR",
    "PHR": "Conclusie",
    "RVS": "ABRvS",
    "CRVB": "CRvB",
    "CBB": "CBb",
}


def _place(name: str | None, kind: str) -> str | None:
    """The place of a rechtbank or gerechtshof from its name: ``Rechtbank Den Haag`` →
    ``Den Haag``."""
    match = re.match(rf"^{kind}\s+(.+)$", (name or "").strip(), re.I)
    return match[1] if match else None


def court_cite(ecli: str, court_name: str | None = None) -> str:
    """The court as it is cited, from the court code of the ECLI and, for a rechtbank or
    hof, its place from the name (given, else the official name of the code,
    ``core.courts``): HR, Conclusie (the Parket), ABRvS, CRvB, CBb, Hof Amsterdam,
    Rb. Den Haag, HvJ EU, Gerecht EU, EHRM."""
    country = country_code(ecli) or ""
    code = court_code(ecli) or ""
    if country == "CE" and code == CODE_ECHR:
        return "EHRM"
    if country == "EU":
        return "Gerecht EU" if code == "T" else "HvJ EU"
    if code in _FIXED:
        return _FIXED[code]
    court = court_of(code, court_name)
    name = (court_name or "").strip() or (court.name if court else "")
    if code.startswith("GH"):
        place = _place(name, "Gerechtshof")
        return f"Hof {place}" if place else "Hof"
    if code.startswith("RB"):
        place = _place(name, "Rechtbank")
        return f"Rb. {place}" if place else "Rb."
    return name or code


def author_cite(name: str | None, role: str | None = None) -> str | None:
    """Who wrote a conclusion as a citation names them: ``A-G Hartlief`` from ``T.
    Hartlief`` (the initials go); ``P-G`` where the role it is signed in
    (``advocate_general_role``) is a procureur-generaal."""
    surname = " ".join(
        part
        for part in (name or "").split()
        if not re.fullmatch(r"([A-Z]\.)+", part)
        and not re.fullmatch(r"mr\.?", part, re.I)
    )
    if not surname:
        return None
    office = "P-G" if "procureur-generaal" in (role or "").lower() else "A-G"
    return f"{office} {surname}"


def judgment_cite(
    ecli: str,
    date: str | None,
    court_name: str | None = None,
    author: str | None = None,
) -> str:
    """``HR 20 december 2019``; a conclusion with its author: ``Conclusie A-G Hartlief 8 mei
    2020``."""
    who = court_cite(ecli, court_name)
    if author:
        who = f"{who} {author}"
    when = long_date(date)
    return f"{who} {when}" if when else who


@dataclass(frozen=True)
class Cite:
    """A judgment cited short (``HR 20 december 2019``) and in full, with its ECLI
    (``HR 20 december 2019, ECLI:NL:HR:2019:2006``)."""

    short: str
    full: str


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def cite_of(props: Mapping[str, Any]) -> Cite | None:
    """The ``Cite`` of a judgment from its props (its own, its light ones or a row of the
    feed): its ``ecli``, its day (``date``, else ``date_eff``), its ``court`` (or the name
    of its code) and, of a conclusion, ``advocate_general`` in their
    ``advocate_general_role``. None without an ECLI."""
    ecli = _text(props.get("ecli"))
    if not ecli:
        return None
    author = author_cite(
        _text(props.get("advocate_general")), _text(props.get("advocate_general_role"))
    )
    short = judgment_cite(
        ecli,
        _text(props.get("date")) or _text(props.get("date_eff")),
        _text(props.get("court")),
        author,
    )
    return Cite(short=short, full=f"{short}, {ecli.upper()}")
