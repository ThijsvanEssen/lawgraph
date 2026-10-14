"""A day as Dutch text writes it (``3 juni 2025``) and as ISO, both ways (pure functions).

Every reader of a Dutch date uses these: the regex fragments to build its own patterns
with, :func:`dutch_day` to read the day a fragment matched. Abbreviated months (``15 sept.
1947``, ``5 mrt 2001``) are read only where a source writes them: ``abbreviations=True``.
"""

from __future__ import annotations

import datetime as dt
import re
from functools import cache

MONTHS = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)
MONTH_ABBREVIATIONS = {
    "jan": 1,
    "febr": 2,
    "feb": 2,
    "mrt": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_NUMBERS = {
    **{month: number for number, month in enumerate(MONTHS, start=1)},
    **MONTH_ABBREVIATIONS,
}
_MONTH = "|".join(MONTHS)
MONTH_OR_ABBREVIATION = "|".join(sorted(_MONTH_NUMBERS, key=len, reverse=True))


def _pattern(months: str, *, year_optional: bool = False, groups: bool = False) -> str:
    """A written day: ``3 juni 2025``, ``15 sept. 1947``, ``8 sep.1977``; with *groups*
    its day, month and year are captured."""
    group = "(" if groups else "(?:"
    year = rf"(?:\s*{group}\d{{4}})(?!\d))" + ("?" if year_optional else "")
    return rf"(?<!\d){group}\d{{1,2}})\s*{group}{months})\b\.?{year}"


# Fragments without groups, to build other patterns with: a day with its year, the same
# with abbreviated months, and a day whose year may be left out (``5 juli``).
DATE = _pattern(_MONTH)
DATE_ABBREVIATED = _pattern(MONTH_OR_ABBREVIATION)
DATE_YEAR_OPTIONAL = _pattern(_MONTH, year_optional=True)


@cache
def _finder(abbreviations: bool, year_optional: bool) -> re.Pattern[str]:
    months = MONTH_OR_ABBREVIATION if abbreviations else _MONTH
    return re.compile(
        _pattern(months, year_optional=year_optional, groups=True), re.IGNORECASE
    )


def dutch_day(
    text: str | None, *, year: int | None = None, abbreviations: bool = False
) -> str | None:
    """The first day written in *text*, as ``YYYY-MM-DD``; a day without its year is of
    *year* when one is given. None when there is none, or it does not exist (``31
    februari``)."""
    found = _finder(abbreviations, year is not None).search(text or "")
    if found is None:
        return None
    day, month, of_year = found.groups()
    try:
        return dt.date(
            int(of_year or year or 0), _MONTH_NUMBERS[month.lower()], int(day)
        ).isoformat()
    except ValueError:
        return None


def long_date(iso: object) -> str:
    """``2019-12-20`` as the explorer writes a day (``langeDatum``): ``20 december 2019``;
    empty for anything that is no date."""
    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})", iso.strip() if isinstance(iso, str) else ""
    )
    if not m:
        return ""
    year, month, day = int(m[1]), int(m[2]), int(m[3])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{day} {MONTHS[month - 1]} {year}"
