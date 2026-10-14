"""A Dutch date as each reader of one reads it today (pinned before they become one)."""

from __future__ import annotations

import pytest

from lawgraph.core import echr_citations, ek_changes, judgments, rijksoverheid

# text, rijksoverheid.parse_date, ek_changes.iso_day (year 2023), iso_day (year 0),
# judgments._dutch_date (only three words), the date of an ECHR citation in Dutch.
_TABLE = [
    (
        "3 juni 2025",
        "2025-06-03",
        "2025-06-03",
        "2025-06-03",
        "2025-06-03",
        "2025-06-03",
    ),
    ("3 Juni 2025", "2025-06-03", None, None, "2025-06-03", "2025-06-03"),
    ("7 MEI 2010", "2010-05-07", None, None, "2010-05-07", "2010-05-07"),
    ("31 februari 2024", "2024-02-31", None, None, None, None),
    (
        "29 februari 2024",
        "2024-02-29",
        "2024-02-29",
        "2024-02-29",
        "2024-02-29",
        "2024-02-29",
    ),
    ("15 sept. 1947", "1947-09-15", None, None, None, None),
    ("8 sep.1977", "1977-09-08", None, None, "-", None),
    ("31 aug 1966", "1966-08-31", None, None, None, None),
    ("5 mrt 2001", "2001-03-05", None, None, None, None),
    ("12 febr. 1990", "1990-02-12", None, None, None, None),
    ("5 juli", None, "2023-07-05", None, "-", None),
    ("op 5 juli zei hij", None, "2023-07-05", None, "-", None),
    ("5 juli en 11 juli 2023", "2023-07-11", "2023-07-05", None, "-", "2023-07-11"),
    ("3 foo 2020", None, None, None, None, None),
    ("123 maart 2000", "2000-03-23", "2000-03-23", "2000-03-23", None, None),
    ("0 mei 2000", None, None, None, None, None),
    ("32 mei 2000", None, None, None, None, None),
    ("3juni 2025", "2025-06-03", None, None, "-", None),
]


def _echr(text: str) -> str | None:
    cited = echr_citations.cited_in_dutch(f"EHRM {text}, nr. 22492/93")
    return cited[0].date


@pytest.mark.parametrize(
    (
        "text",
        "rijksoverheid_day",
        "ek_day",
        "ek_day_no_year",
        "judgment_day",
        "echr_day",
    ),
    _TABLE,
)
def test_each_reader_reads_a_day(
    text: str,
    rijksoverheid_day: str | None,
    ek_day: str | None,
    ek_day_no_year: str | None,
    judgment_day: str | None,
    echr_day: str | None,
) -> None:
    assert rijksoverheid.parse_date(text) == rijksoverheid_day
    assert ek_changes.iso_day(text, 2023) == ek_day
    assert ek_changes.iso_day(text, 0) == ek_day_no_year
    if judgment_day != "-":
        assert judgments._dutch_date(text) == judgment_day
    assert _echr(text) == echr_day


def test_the_day_before_and_after_cross_months_and_years() -> None:
    from lawgraph.core.coalition import _next_day
    from lawgraph.core.seat_periods import day_before

    assert day_before("2024-03-01") == "2024-02-29"
    assert day_before("2025-01-01") == "2024-12-31"
    assert _next_day("2023-02-28") == "2023-03-01"
    assert _next_day("2024-12-31") == "2025-01-01"
