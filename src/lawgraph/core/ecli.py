"""The ECLIs a text names, checked for their syntax and repaired where the text shows what was
meant (pure, no I/O).

An ECLI is ``ECLI:<country>:<court>:<year>:<number>``. One is valid when its country is one
that issues ECLIs, its court code has the shape of one (a Dutch one is letters), its year lies
between 1900 and the current year and its number has the shape of one: a Dutch number is a
number or an LJN (two letters and four digits), another country's an alphanumeric ordinal
that may hold dots, underscores or hyphens. Whether a court code exists is not checked here.

What a text shows is repaired: an LJN whose digits the text sets apart ("BH 2815",
"BH:4033"), a number set apart from its year ("2019: 322"), NL and the court swapped
("ECLI:HR:NL:2023:26"), a range ("2018:2374-2375") that is its members, a word glued to the
number ("661verworpen", "BV2954.vgl") or the next ECLI glued to it, and a zero or one typed
for a letter of an LJN ("A09006"). Anything else that is not valid is dropped.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator

# The countries (ISO 3166 codes, EL for Greece) of the ECLI Council conclusions
# (2011/C 127/01, revised in 2019/C 360/01), EU for the courts of the Union, CE for the
# Council of Europe and EP for the boards of appeal of the European Patent Office.
ECLI_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "GR", "HR",
        "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        "CE", "EP", "EU",
    }
)  # fmt: skip
FIRST_YEAR = 1900
# The longest range read as its members.
MAX_RANGE = 20

_DUTCH_COURT = re.compile(r"[A-Z]{1,7}")
_COURT = re.compile(r"[A-Z][A-Z0-9]{0,6}")
_DUTCH_NUMBER = re.compile(r"\d{1,6}|[A-Z]{2}\d{4}")
_NUMBER = re.compile(r"[A-Z0-9]+(?:[._-][A-Z0-9]+)*")
_LJN = re.compile(r"[A-Z]{2}\d{4}")
# A word glued to a Dutch number: "661VERWORPEN", "BV2954.VGL".
_GLUED = re.compile(r"(\d{1,6}|[A-Z]{2}\d{4})\.?[A-Z]+")
# "LJN:BX7991" where the number goes.
_LJN_LABEL = re.compile(r":(?P<ljn>[A-Z]{2}\d{4})\b", re.IGNORECASE)

# An ECLI as a text writes it: a space may follow the colon before the number.
_CANDIDATE = re.compile(
    r"\bECLI:(?P<country>[A-Z]{2}):(?P<court>[A-Z0-9]+):(?P<year>\d{4}):\s?"
    r"(?!ECLI:)(?P<number>[A-Z0-9]+(?:[._-][A-Z0-9]+)*)\b",
    re.IGNORECASE,
)
# The next ECLI glued to the one before: "695ECLI:NL:..." or "1998:ECLI:NL:...".
_GLUED_ECLI = re.compile(r"(?<=[A-Z0-9.:])(?=ECLI:)", re.IGNORECASE)
# The digits of an LJN set apart: "BH 2815", "BH:4033".
_LJN_DIGITS = re.compile(r"(?:\s{1,3}|:)(?P<digits>\d{1,4})\b")
# The end of a range set apart: "992 - 995".
_RANGE_END = re.compile(r"\s?[-–]\s?(?P<end>\d{1,6})\b")


def is_valid_ecli(ecli: str, *, this_year: int | None = None) -> bool:
    """True for an ECLI of the right syntax (see the module); the court code is not looked up."""
    parts = ecli.strip().upper().split(":")
    if len(parts) != 5 or parts[0] != "ECLI":
        return False
    _, country, court, year, number = parts
    if country not in ECLI_COUNTRIES or not year.isdigit():
        return False
    if not FIRST_YEAR <= int(year) <= (this_year or dt.date.today().year):
        return False
    if country == "NL":
        return bool(_DUTCH_COURT.fullmatch(court) and _DUTCH_NUMBER.fullmatch(number))
    return bool(_COURT.fullmatch(court) and _NUMBER.fullmatch(number))


def cited_eclis(text: str | None) -> list[str]:
    """The valid ECLIs *text* names, repaired where it shows what was meant, upper-cased and
    once each, in the order of their first appearance."""
    if not text:
        return []
    text = _GLUED_ECLI.sub(" ", text)
    found: dict[str, None] = {}
    for match in _CANDIDATE.finditer(text):
        for ecli in _repaired(match, text[match.end() : match.end() + 12]):
            if is_valid_ecli(ecli):
                found.setdefault(ecli)
    return list(found)


def _repaired(match: re.Match[str], after: str) -> Iterator[str]:
    """The ECLIs a candidate stands for, given the text right *after* it; not yet checked."""
    country, court, year, number = (
        match.group(name).upper() for name in ("country", "court", "year", "number")
    )
    if court == "NL" and country != "NL":
        country, court = court, country
    prefix = f"ECLI:{country}:{court}:{year}:"
    if country != "NL":
        yield prefix + number
        return
    for dutch in _dutch_numbers(number, after):
        yield prefix + dutch


def _dutch_numbers(number: str, after: str) -> list[str]:
    """What a Dutch number stands for: the members of a range, a completed or corrected LJN,
    the number without a word glued to it, or the number as it is."""
    if number == "LJN":
        label = _LJN_LABEL.match(after)
        return [label.group("ljn").upper()] if label else []
    if "-" in number:
        start, _, end = number.partition("-")
        return _range(start, end)
    if number.isdigit():
        range_end = _RANGE_END.match(after)
        return _range(number, range_end.group("end")) if range_end else [number]
    return [_completed_ljn(number, after)]


def _range(start: str, end: str) -> list[str]:
    """The numbers from *start* to *end*; none for what is no short ascending range."""
    if not (start.isdigit() and end.isdigit()):
        return []
    first, last = int(start), int(end)
    if not first < last <= first + MAX_RANGE:
        return []
    return [str(n) for n in range(first, last + 1)]


def _completed_ljn(number: str, after: str) -> str:
    """An LJN with the digits the text sets apart joined to it, a zero or one read as the
    letter it stands for (and a letter as the digit), a glued word cut off."""
    digits = _LJN_DIGITS.match(after)
    if digits and re.fullmatch(r"[A-Z]{2}\d{0,3}", number):
        joined = number + digits.group("digits")
        if _LJN.fullmatch(joined):
            return joined
    if len(number) == 6 and number[0].isalpha():
        typed = (
            number[0]
            + number[1].replace("0", "O").replace("1", "I")
            + number[2:].replace("O", "0").replace("I", "1")
        )
        if _LJN.fullmatch(typed):
            return typed
    glued = _GLUED.fullmatch(number)
    return glued.group(1) if glued else number
