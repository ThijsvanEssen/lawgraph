"""A Dutch day is read and written in ``core/dutch_dates``; an ISO day is shifted, and a
period left open, with ``core/time``.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from tests.paths import SRC
from tests.source_scan import python_files, string_literals

# The homes: Dutch month names in ``core/dutch_dates.py``; shifting an ISO day and the open
# end of a period in ``core/time.py``.
DUTCH_DATES_HOME = SRC / "core" / "dutch_dates.py"
TIME_HOME = SRC / "core" / "time.py"
_MONTH_WORDS = (
    "januari februari maart april mei juni juli augustus september oktober november "
    "december jan feb febr mrt apr jun jul aug sep sept okt nov dec"
).split()
# The months only Dutch spells so (not ``april``, ``september``: English has them too).
_FULL_MONTH = re.compile(
    r"\b(?:januari|februari|maart|mei|juni|juli|augustus|oktober)\b", re.IGNORECASE
)
_SHIFTED_ISO_DAY = re.compile(r"fromisoformat\([^()]*\)\s*[-+]\s*(?:dt\.)?timedelta\(")


def _date_copies(source: str) -> list[str]:
    """What in *source* writes a month table, the open end, or shifts an ISO day by hand."""
    found = []
    for _, text in string_literals(ast.parse(source), pieces=True):
        if text.lower() in _MONTH_WORDS:
            found.append(f"month {text!r}")
        elif len({m.lower() for m in _FULL_MONTH.findall(text)}) > 1:
            found.append(f"months in {text[:40]!r}")
        elif text == "9999-12-31":
            found.append("the open end (time.OPEN_END)")
    found += [f"shifted day {m[0]!r}" for m in _SHIFTED_ISO_DAY.finditer(source)]
    return found


def test_the_date_scan_would_catch_a_copy() -> None:
    assert _date_copies('MONTHS = ("januari", "februari")') == [
        "month 'januari'",
        "month 'februari'",
    ]
    assert _date_copies('M = "maart|mei"') == ["months in 'maart|mei'"]
    assert _date_copies('def f():\n    """Van 3 juli tot 4 augustus."""') == []
    assert _date_copies('END = "9999-12-31"') == ["the open end (time.OPEN_END)"]
    assert _date_copies("d = dt.date.fromisoformat(x) - dt.timedelta(days=1)") == [
        "shifted day 'fromisoformat(x) - dt.timedelta('"
    ]


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_dates_are_read_and_shifted_in_one_place(path: pathlib.Path) -> None:
    if path in (DUTCH_DATES_HOME, TIME_HOME):
        return
    copies = _date_copies(path.read_text())
    assert not copies, (
        f"{path.relative_to(SRC)} has {copies}; use core/dutch_dates.py "
        f"(MONTHS, DATE, dutch_day) or core/time.py (shift_day, day_before, OPEN_END)."
    )
