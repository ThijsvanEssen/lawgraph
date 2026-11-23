"""The numbers in the text of an article: amounts, percentages, time limits and dates.

Read from the text of an ArticleVersion as normalize wrote it, with its parts, tables and
redactions (offsets into the text), so every value is that of the toestand the version
holds: a new toestand with another amount is a new version, and its value comes with it.
No value is a constant of the code.

What is read (a space may be a no-break space, as the BWB writes them):

* an amount: ``€ 3.115``, ``€ 102.000,00``, ``€ 1.000,–``, ``€ 22,5 miljoen``, the old
  notation ``€ 3 350``, and ``227 euro``; in euros;
* a percentage: ``6,398%``, ``20 procent``, ``vijf procent``;
* a time limit: a number (in figures or words) and a unit (``dag``, ``werkdag``, ``week``,
  ``maand``, ``jaar``, ``uur``) after a word that makes it one: ``binnen zes weken``,
  ``ten minste een maand``, ``termijn van twee maanden``, and "De termijn … bedraagt zes
  weken" (art. 6:7 Awb). Not after a penalty or an age ("gevangenisstraf van ten hoogste
  negen jaren", "zestien jaar of ouder") and not a rate ("twaalf uur per week");
* a date after ``vóór``, ``per`` or ``met ingang van``: ``1 januari 2027``, or a day of every
  year (``vóór 1 april``: ``--04-01``). A date in the title of a regulation it cites
  ("Verordening … van 27 april 2016") is no value.

A redaction that opens with its date ("per 1 juli 2026: € 14,99", art. 8 Wml) gives the
values in it that date as ``valid_from`` and the source ``redaction``: the value in force
from then on; the amount the law prints before it stays a value of its own (``text``).
A value in a table names its cell (row and cell of its line). What is in doubt is not read:
an amount in words, a fraction ("33 1/3%"), a number without such a word.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from lawgraph.core.dutch_dates import MONTHS

KIND_AMOUNT = "bedrag"
KIND_PERCENTAGE = "percentage"
KIND_TERM = "termijn"
KIND_DATE = "datum"
SOURCE_TEXT = "text"
SOURCE_REDACTION = "redaction"

_SP = "[ \\u00a0]"
_ONES = "een twee drie vier vijf zes zeven acht negen".split()
_TEENS = (
    "tien elf twaalf dertien veertien vijftien zestien zeventien achttien negentien"
)
_TENS = "twintig dertig veertig vijftig zestig zeventig tachtig negentig".split()


def _number_words() -> dict[str, int]:
    """Each number in words up to a hundred: ``een`` 1, ``achtentwintig`` 28."""
    words = {word: n for n, word in enumerate(_ONES + _TEENS.split(), start=1)}
    words["één"] = 1
    for t, ten in enumerate(_TENS, start=2):
        words[ten] = 10 * t
        for o, one in enumerate(_ONES, start=1):
            joint = "ën" if one.endswith("e") else "en"
            words[f"{one}{joint}{ten}"] = 10 * t + o
    words["honderd"] = 100
    return words


_WORDS = _number_words()
_MONTH = "|".join(MONTHS)

_EURO = re.compile(
    rf"€{_SP}?(?P<int>\d{{1,3}}(?:(?:\.|{_SP})\d{{3}}(?!\d))+|\d+)"
    rf"(?:,(?P<cents>\d{{1,2}}(?!\d)|[–-]))?(?:{_SP}(?P<mult>miljoen|miljard)\b)?"
    rf"|(?<![\d.,])(?P<int2>\d{{1,3}}(?:\.\d{{3}})+|\d+)(?:,(?P<cents2>\d{{2}}))?{_SP}euro\b"
)
_PERCENT = re.compile(
    rf"(?<![\d,/])(?P<num>\d+(?:,\d+)?)(?:{_SP}?%|{_SP}(?:procent|percent)\b)"
    rf"|\b(?P<word>[a-zé]+){_SP}(?:procent|percent)\b",
    re.IGNORECASE,
)
_TERM_WORDS = (
    "binnen|na|vóór|voor|uiterlijk|gedurende|ten minste|ten hoogste|termijn van|"
    "verloop van|periode van|tijdvak van|langer dan|korter dan|niet later dan|"
    "niet eerder dan|bedraagt"
)
_TERM = re.compile(
    rf"\b(?P<lead>{_TERM_WORDS}){_SP}(?P<num>\d+|[a-zéë]+){_SP}"
    r"(?P<unit>(?:kalender)?(?:werkdagen|werkdag|dagen|dag|weken|week|maanden|maand|"
    r"jaren|jaar)|uren|uur)\b",
    re.IGNORECASE,
)
_UNITS = {
    "werkdagen": "werkdag",
    "dagen": "dag",
    "weken": "week",
    "maanden": "maand",
    "jaren": "jaar",
    "uren": "uur",
}
# What makes a number of years no time limit: a penalty or an age before it, an age or a
# rate after it.
_NOT_A_TERM_BEFORE = re.compile(r"(?:straf|hechtenis|leeftijd)\b[^.;]{0,40}$", re.I)
_NOT_A_TERM_AFTER = re.compile(rf"^{_SP}(?:of ouder|of jonger|en ouder|oud\b|per\b)")
# "De termijn … bedraagt zes weken": ``bedraagt`` leads a time limit only after "termijn".
_TERM_BEFORE = re.compile(r"termijn[^.;]{0,120}$", re.I)
_DATE = re.compile(
    rf"(?P<lead>\b(?:vóór|per|met ingang van)){_SP}(?P<day>\d{{1,2}}){_SP}"
    rf"(?P<month>{_MONTH})(?:{_SP}(?P<year>\d{{4}}))?\b",
    re.IGNORECASE,
)
# The opening of a redaction that names the day its values hold from.
_REDACTION_HEAD = re.compile(
    rf"per{_SP}(?P<day>\d{{1,2}}){_SP}(?P<month>{_MONTH}){_SP}(?P<year>\d{{4}})",
    re.IGNORECASE,
)
_MULTIPLIERS = {"miljoen": Decimal(10**6), "miljard": Decimal(10**9)}


@dataclass(frozen=True)
class Found:
    """A value in the text: its span, what it is and its value."""

    start: int
    end: int
    kind: str
    unit: str
    value: Decimal | None = None
    date: str | None = None


@dataclass(frozen=True)
class Amount:
    """A value of an ArticleVersion, a row of ``lg_amounts``: *part* the id of the
    innermost part that holds it (None in an article without parts), *valid_from* the day
    of the redaction it stands in (None: the version's own), *cell* its row and cell when
    it stands in a table."""

    found: Found
    part: str | None
    source: str
    valid_from: str | None = None
    cell: tuple[int, int] | None = None

    def to_row(self) -> dict[str, Any]:
        """The columns of its row in ``lg_amounts``, without the version."""
        found = self.found
        return {
            "span_start": found.start,
            "span_end": found.end,
            "part": self.part,
            "kind": found.kind,
            "value": None if found.value is None else str(found.value),
            "unit": found.unit,
            "date": found.date,
            "source": self.source,
            "valid_from": self.valid_from,
            "cell": list(self.cell) if self.cell else None,
        }


def _decimal(number: str) -> Decimal:
    """A number as the law prints it: ``3.115`` and ``3 350`` are thousands, ``6,398`` a
    decimal comma."""
    return Decimal(re.sub(r"[.\s]", "", number).replace(",", "."))


def _euros(match: re.Match[str]) -> Decimal:
    whole = match["int"] or match["int2"]
    cents = match["cents"] or match["cents2"] or ""
    value = _decimal(whole)
    if cents.isdigit():
        value += Decimal(cents) / Decimal(10 ** len(cents))
    return value * _MULTIPLIERS.get(match["mult"] or "", Decimal(1))


def _count(number: str) -> int | None:
    """A number in figures or words; None for a word that is none."""
    return int(number) if number.isdigit() else _WORDS.get(number.lower())


def _day(day: str, month: str, year: str | None) -> str | None:
    """``2027-01-01``, or ``--04-01`` for a day of every year; None for no day."""
    m = MONTHS.index(month.lower()) + 1
    try:
        dt.date(int(year or 2000), m, int(day))  # 2000: 29 februari is a day
    except ValueError:
        return None
    return f"{year}-{m:02}-{int(day):02}" if year else f"--{m:02}-{int(day):02}"


def _amounts(text: str) -> Iterator[Found]:
    for m in _EURO.finditer(text):
        yield Found(m.start(), m.end(), KIND_AMOUNT, "EUR", _euros(m))
    for m in _PERCENT.finditer(text):
        value = _decimal(m["num"]) if m["num"] else _count(m["word"])
        if value is not None:
            yield Found(m.start(), m.end(), KIND_PERCENTAGE, "%", Decimal(value))


def _is_term(text: str, m: re.Match[str]) -> bool:
    before, after = (
        text[max(m.start() - 160, 0) : m.start()],
        text[m.end() : m.end() + 12],
    )
    if _NOT_A_TERM_BEFORE.search(before) or _NOT_A_TERM_AFTER.match(after):
        return False
    return m["lead"].lower() != "bedraagt" or bool(_TERM_BEFORE.search(before))


def _terms(text: str) -> Iterator[Found]:
    for m in _TERM.finditer(text):
        count = _count(m["num"])
        if count is None or not _is_term(text, m):
            continue
        unit = m["unit"].lower().removeprefix("kalender")
        found = Found(m.start("num"), m.end(), KIND_TERM, _UNITS.get(unit, unit))
        yield replace(found, value=Decimal(count))


def _dates(text: str) -> Iterator[Found]:
    for m in _DATE.finditer(text):
        day = _day(m["day"], m["month"], m["year"])
        if day:
            yield Found(m.start("day"), m.end(), KIND_DATE, "datum", date=day)


def values(text: str) -> list[Found]:
    """The values in *text* by their place; of two that overlap the first."""
    found = sorted([*_amounts(text), *_terms(text), *_dates(text)], key=_place)
    kept: list[Found] = []
    for value in found:
        if not kept or value.start >= kept[-1].end:
            kept.append(value)
    return kept


def _place(found: Found) -> tuple[int, int]:
    return found.start, -found.end


def _part(parts: Sequence[Mapping[str, Any]], found: Found) -> str | None:
    """The id of the innermost part that holds *found* (parts by start, enclosing first)."""
    holder = None
    for part in parts:
        if part["start"] <= found.start and found.end <= part["end"]:
            holder = part["id"]
    return holder


def _cell(
    text: str, tables: Sequence[Mapping[str, Any]], found: Found
) -> tuple[int, int] | None:
    """Row and cell of *found* in the table that holds it: a row a line, a cell a tab."""
    for table in tables:
        if table["start"] <= found.start and found.end <= table["end"]:
            line = text.rfind("\n", table["start"], found.start) + 1 or table["start"]
            row = text.count("\n", table["start"], found.start)
            return row, text.count("\t", max(line, table["start"]), found.start)
    return None


def _redaction(
    text: str, redactions: Sequence[Mapping[str, Any]], found: Found
) -> tuple[bool, str | None, bool]:
    """Whether *found* stands in a redaction, the day the redaction holds from, and whether
    *found* is that day itself (the head of the redaction, no value)."""
    for redaction in redactions:
        start, end = redaction["start"], redaction["end"]
        if start <= found.start and found.end <= end:
            head = _REDACTION_HEAD.match(text, start, end)
            if head is None:
                return True, None, False
            day = _day(head["day"], head["month"], head["year"])
            return True, day, found.start < head.end()
    return False, None, False


def amounts(
    text: str,
    parts: Sequence[Mapping[str, Any]] = (),
    tables: Sequence[Mapping[str, Any]] = (),
    redactions: Sequence[Mapping[str, Any]] = (),
) -> list[Amount]:
    """The values of the text of an ArticleVersion, with the props that hold its
    structure (``parts``, ``tables``, ``redactions``: offsets into *text*)."""
    rows = []
    for found in values(text):
        redacted, day, head = _redaction(text, redactions, found)
        if head:
            continue
        rows.append(
            Amount(
                found,
                _part(parts, found),
                SOURCE_REDACTION if redacted else SOURCE_TEXT,
                day,
                _cell(text, tables, found),
            )
        )
    return rows
