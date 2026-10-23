"""The days of an advice of the Raad van State, as its paper writes them (pure).

The Tweede Kamer dates a paper by the day it was filed (``Document.Datum``), which for the
advice of the Afdeling advisering is the day the bill was submitted, months after the advice.
The paper itself opens with the days: ``Hieronder zijn opgenomen het advies van de Afdeling
advisering van de Raad van State d.d. 15 november 2023 en het nader rapport d.d. 2 februari
2024``. Those are the days of the advice and of the nader rapport.
"""

from __future__ import annotations

import re
from typing import Final

from lawgraph.core.dutch_dates import DATE, dutch_day
from lawgraph.core.tk_records.kinds import KIND_ADVICE

# How far into the text the opening sentence is looked for.
_OPENING_CHARS: Final = 3000

_ADVICE = re.compile(
    rf"\badvies\b[^.]{{0,120}}?Raad\s+van\s+State\s+(?:d\.d\.|van|gedateerd)\s+({DATE})",
    re.IGNORECASE,
)
_REPORT = re.compile(rf"\bnader\s+rapport\s+(?:d\.d\.|van|gedateerd)\s+({DATE})", re.I)


def is_advice(kind: str | None) -> bool:
    """A ``Soort`` of an advice of the Afdeling advisering, also one with its nader rapport
    or the reaction of the initiator."""
    return (kind or "").startswith(KIND_ADVICE)


def read_advice_days(text: str) -> dict[str, str | None]:
    """``{advice_date, report_date}`` of the opening of an advice paper: the day of the
    advice and of the nader rapport, ISO; None for a day the opening does not give."""
    opening = text[:_OPENING_CHARS]
    advice, report = _ADVICE.search(opening), _REPORT.search(opening)
    return {
        "advice_date": dutch_day(advice.group(1)) if advice else None,
        "report_date": dutch_day(report.group(1)) if report else None,
    }
