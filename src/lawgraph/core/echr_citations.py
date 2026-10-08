"""The decisions of the ECHR a text cites by application number (pure: no I/O, no store).

A Dutch judgment cites Strasbourg by court, date and application number: "EHRM 28 maart 2000,
nr. 22492/93 (Kiliç/Turkije)", "EHRM (GK) 12 november 2008, nrs. 34503/97 en 34504/97". A
judgment of the ECHR cites another by name and number, the date often left out: "Kılıç v.
Turkey, no. 22492/93, § 62, ECHR 2000-III", "(dec.), no. 12345/01, 3 May 2005". An application
number alone does not name one decision: a case has its decision on admissibility, the judgment
of the Chamber and that of the Grand Chamber, each of another date. So a citation with a date
names the decision of that number and date, one without a date only the one decision of its
number, if it has one; any other is left (``resolve``).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from enum import Enum

# An application number: "22492/93", "123/04".
_APPNO = r"\d{1,6}/\d{2}"
_MONTHS_NL = (
    "januari februari maart april mei juni juli augustus september oktober november "
    "december"
).split()
_MONTHS_EN = (
    "january february march april may june july august september october november december"
).split()
_DATE_NL = re.compile(rf"\b(\d{{1,2}})\s+({'|'.join(_MONTHS_NL)})\s+(\d{{4}})\b", re.I)
_DATE_EN = re.compile(rf"\b(\d{{1,2}})\s+({'|'.join(_MONTHS_EN)})\s+(\d{{4}})\b", re.I)
# "EHRM", "EHRM (GK)", "EHRM (dec.)": the start of a Dutch citation of the Court.
_COURT_NL = re.compile(r"\bEHRM\b")
# The numbers after "nr.", "nrs.", "no.", "nos.", "application": one, or a list of them.
_NUMBERS = re.compile(
    rf"\b(?:nrs?|nos?|application(?:s)?(?:\s+nos?)?)\.?\s*"
    rf"({_APPNO}(?:\s*(?:,|en|and|&)\s*{_APPNO})*)",
    re.I,
)
# How far after "EHRM" a Dutch citation names its numbers: its date, the parties, a chamber.
_NL_WINDOW = 160
# How far after the numbers a citation of the Court names its date, before the next one.
_EN_WINDOW = 80


@dataclass(frozen=True)
class Cited:
    """One decision a text cites: an application number, the date when the text gives it."""

    appno: str
    date: str | None = None


class Unresolved(Enum):
    MISSING = "missing"  # no decision of that number is loaded
    AMBIGUOUS = "ambiguous"  # several decisions of that number, and no date to choose


def _date(match: re.Match[str] | None, months: list[str]) -> str | None:
    if match is None:
        return None
    try:
        month = months.index(match[2].lower()) + 1
        return dt.date(int(match[3]), month, int(match[1])).isoformat()
    except ValueError:
        return None


def _numbers(text: str) -> list[str]:
    return re.findall(_APPNO, text)


def cited_in_dutch(text: str) -> list[Cited]:
    """The decisions a Dutch text cites: after each "EHRM", its date (if it comes before the
    numbers) and the numbers named with "nr." or "nrs."."""
    found: list[Cited] = []
    for court in _COURT_NL.finditer(text):
        window = text[court.end() : court.end() + _NL_WINDOW]
        numbers = _NUMBERS.search(window)
        if numbers is None:
            continue
        date = _date(_DATE_NL.search(window[: numbers.start()]), _MONTHS_NL)
        found += [Cited(appno, date) for appno in _numbers(numbers[1])]
    return _distinct(found)


def cited_in_english(text: str, *, own: frozenset[str] = frozenset()) -> list[Cited]:
    """The decisions a judgment of the Court cites: each "no." or "nos." and its numbers,
    with a date that follows within the citation; not its own numbers (*own*)."""
    found: list[Cited] = []
    for numbers in _NUMBERS.finditer(text):
        after = text[numbers.end() : numbers.end() + _EN_WINDOW]
        after = re.split(r"[;)]", after, maxsplit=1)[0]
        date = _date(_DATE_EN.search(after), _MONTHS_EN)
        found += [
            Cited(appno, date) for appno in _numbers(numbers[1]) if appno not in own
        ]
    return _distinct(found)


def _distinct(cited: list[Cited]) -> list[Cited]:
    """Each citation once; a number cited with a date and without counts with the date."""
    dated = {c.appno for c in cited if c.date}
    seen: dict[Cited, None] = {}
    for c in cited:
        if c.date or c.appno not in dated:
            seen.setdefault(c, None)
    return list(seen)


def appnos(field: str | None) -> list[str]:
    """The application numbers of a decision's ``appno`` field: "7481/23;7493/23"."""
    return re.findall(_APPNO, field or "")


def resolve(
    cited: Cited, decisions: dict[str, list[tuple[str | None, str]]]
) -> str | Unresolved:
    """The node id of the decision *cited* names, from *decisions* (application number ->
    ``(date, id)`` of each decision of it, one per decision): of that date when it has one,
    else the only decision of its number."""
    candidates = decisions.get(cited.appno, [])
    if cited.date:
        candidates = [c for c in candidates if c[0] == cited.date]
    ids = sorted({node_id for _, node_id in candidates})
    if not ids:
        return Unresolved.MISSING
    if len(ids) > 1:
        return Unresolved.AMBIGUOUS
    return ids[0]


def decisions_by_appno(
    rows: list[dict[str, str | None]],
) -> dict[str, list[tuple[str | None, str]]]:
    """Application number -> ``(date, id)`` of each decision of it, from rows of ``{id,
    appno, date}``: the index ``resolve`` reads."""
    index: dict[str, list[tuple[str | None, str]]] = {}
    for row in rows:
        for appno in appnos(row.get("appno")):
            index.setdefault(appno, []).append((row.get("date"), str(row["id"])))
    return index
