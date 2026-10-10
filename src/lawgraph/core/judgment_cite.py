"""A judgment as a lawyer cites it (pure): the court in its usual short form, the day in full,
then the ECLI. ``HR 20 december 2019``, ``Rb. Den Haag 6 juli 2026``, ``Conclusie A-G
Hartlief 8 mei 2020``. The same rules as the explorer's ``judgment-cite.ts``, so a title the
API gives reads as the app cites."""

from __future__ import annotations

import re

from lawgraph.core.time import long_date

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
    hof, its place from the name: HR, Conclusie (the Parket), ABRvS, CRvB, CBb, Hof
    Amsterdam, Rb. Den Haag, HvJ EU, EHRM."""
    parts = ecli.strip().upper().split(":")
    country = parts[1] if len(parts) > 1 else ""
    code = parts[2] if len(parts) > 2 else ""
    if country == "CE" and code == "ECHR":
        return "EHRM"
    if country == "EU":
        return "Gerecht EU" if code == "T" else "HvJ EU"
    if code in _FIXED:
        return _FIXED[code]
    if code.startswith("GH"):
        place = _place(court_name, "Gerechtshof")
        return f"Hof {place}" if place else "Hof"
    if code.startswith("RB"):
        place = _place(court_name, "Rechtbank")
        return f"Rb. {place}" if place else "Rb."
    return (court_name or "").strip() or code


def author_cite(name: str | None) -> str | None:
    """The advocate-general of a conclusion as a citation names them: ``A-G Hartlief``
    from ``T. Hartlief`` (the initials go)."""
    surname = " ".join(
        part
        for part in (name or "").split()
        if not re.fullmatch(r"([A-Z]\.)+", part)
        and not re.fullmatch(r"mr\.?", part, re.I)
    )
    return f"A-G {surname}" if surname else None


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
