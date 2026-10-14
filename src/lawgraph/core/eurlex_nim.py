"""The publication a national implementing measure of EUR-Lex (CELLAR) is — pure, no I/O.

CELLAR records a Dutch measure by the official journal it appeared in ("Staatsblad (Bulletin
des Lois et des Décrets royaux)", "Staatscourant (…)"), its number in that journal and the
date of that journal. The publication is the one the BWB names as the origin of an article
version: ``stb-2018-401``. What CELLAR writes varies with the years:

* the number alone (``401``), or number and year in either order (``178/2002``, ``2005/24``,
  ``2025, 449``), or the KOOP id (``stb-2025-449``);
* no journal (most measures of the last years): the kind of act says it where the
  Bekendmakingswet leaves no choice, a wet in the Staatsblad, a ministeriële regeling in the
  Staatscourant;
* no date, when the title says the year next to the number ("Staatsblad 1992, nr. 329",
  "Staatsblad nummer 603 van 1997"); ``1001-01-01`` is its placeholder for an unknown date.

A measure in another journal ("Administrative measures"), or whose number or year cannot be
read, names no publication.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from lawgraph.core.publications import (
    PublicationSeries,
    koop_citation,
    koop_id,
    parse_koop_id,
)

# The journal (its first word, as CELLAR names it) -> the kind in a KOOP publication id.
_JOURNAL_KINDS: dict[str, PublicationSeries] = {
    "staatsblad": "stb",
    "staatscourant": "stcrt",
}
# The kind of act (``type``, as CELLAR names it) -> the journal the law places it in.
_ACT_JOURNALS: dict[str, PublicationSeries] = {
    "wet": "stb",
    "ministeriele regeling": "stcrt",
}
_NUMBER = re.compile(r"^(\d+)(?:\s*[/,]\s*(\d+))?$")
_DATE_YEAR = re.compile(r"^(\d{4})-\d\d-\d\d")
_FIRST_YEAR = 1900  # CELLAR's placeholder for an unknown date is the year 1001
# The year next to the number in the title: "Staatsblad 1992, nr. 329", "Staatsblad 1999,
# 122", "Staatsblad nummer 603 van 1997".
_TITLE_YEAR_NUMBER = re.compile(
    r"(?:Staatsblad|Staatscourant)\s+(?P<year>\d{4}),?\s*(?:nr\.?|nummer)?\s*(?P<nr>\d+)",
    re.IGNORECASE,
)
_TITLE_NUMBER_YEAR = re.compile(
    r"(?:Staatsblad|Staatscourant)\s+(?:nr\.?|nummer)\s*(?P<nr>\d+)\s+van\s+(?P<year>\d{4})",
    re.IGNORECASE,
)


def measure_summary(measure: Mapping[str, Any], publication: str) -> dict[str, Any]:
    """What an IMPLEMENTS edge keeps of the measure in *publication*: its publication, how
    that is cited, and the title and kind of act as EUR-Lex gives them."""
    summary = {
        "publication": publication,
        "citation": koop_citation(publication) or publication,
        "title": str(measure.get("title") or "").strip() or None,
        "type": str(measure.get("type") or "").strip() or None,
    }
    return {key: value for key, value in summary.items() if value is not None}


def measure_publication(measure: Mapping[str, Any]) -> str | None:
    """``stb-2018-401`` for a measure of the Staatsblad or Staatscourant, else None."""
    number = str(measure.get("number") or "").strip()
    koop = parse_koop_id(number)
    if koop and koop[0] in _JOURNAL_KINDS.values():
        return koop_id(koop[0], koop[1], int(koop[2]))
    kind = _journal(measure)
    parts = _NUMBER.match(number)
    if not (kind and parts):
        return None
    year = _year(measure, parts[1])
    if year is None:
        return None
    if parts[2] is None:
        return koop_id(kind, year, int(parts[1]))
    # number and year in either order: the part that is not the year is the number
    first, second = parts[1], parts[2]
    if second == year:
        return koop_id(kind, year, int(first))
    if first == year:
        return koop_id(kind, year, int(second))
    return None


def _journal(measure: Mapping[str, Any]) -> PublicationSeries | None:
    """``stb`` or ``stcrt``: the journal CELLAR names, else the one of the kind of act."""
    journal = str(measure.get("journal") or "").strip()
    if journal:
        return _JOURNAL_KINDS.get(journal.split(" ", 1)[0].lower())
    return _ACT_JOURNALS.get(str(measure.get("type") or "").strip().lower())


def _year(measure: Mapping[str, Any], number: str) -> str | None:
    """The year of the journal: of its date, else the one the title gives the number."""
    date = _DATE_YEAR.match(str(measure.get("date") or ""))
    if date:
        return date[1] if int(date[1]) >= _FIRST_YEAR else None
    title = str(measure.get("title") or "")
    for pattern in (_TITLE_YEAR_NUMBER, _TITLE_NUMBER_YEAR):
        for match in pattern.finditer(title):
            if int(match["nr"]) == int(number) and int(match["year"]) >= _FIRST_YEAR:
                return match["year"]
    return None
