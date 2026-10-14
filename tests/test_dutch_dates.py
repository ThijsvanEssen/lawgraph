"""A day as Dutch text writes it, read and written in one place."""

from __future__ import annotations

import re

import pytest

from lawgraph.core.dutch_dates import (
    DATE,
    DATE_ABBREVIATED,
    DATE_YEAR_OPTIONAL,
    dutch_day,
    long_date,
)
from lawgraph.core.time import day_before, shift_day

# text; read with abbreviations (the Rijksoverheid and Eerste Kamer pages), of the year
# 2023 when it leaves the year out (an Eerste Kamer news item), and plain (judgments).
_TABLE = [
    ("3 juni 2025", "2025-06-03", "2025-06-03", "2025-06-03"),
    ("3 Juni 2025", "2025-06-03", "2025-06-03", "2025-06-03"),
    ("7 MEI 2010", "2010-05-07", "2010-05-07", "2010-05-07"),
    ("3juni 2025", "2025-06-03", "2025-06-03", "2025-06-03"),
    ("sinds10 augustus 2021", "2021-08-10", "2021-08-10", "2021-08-10"),
    ("29 februari 2024", "2024-02-29", "2024-02-29", "2024-02-29"),
    ("31 februari 2024", None, None, None),
    ("0 mei 2000", None, None, None),
    ("32 mei 2000", None, None, None),
    ("3 foo 2020", None, None, None),
    ("123 maart 2000", None, None, None),
    ("15 sept. 1947", "1947-09-15", None, None),
    ("8 sep.1977", "1977-09-08", None, None),
    ("31 aug 1966", "1966-08-31", None, None),
    ("5 mrt 2001", "2001-03-05", None, None),
    ("12 febr. 1990", "1990-02-12", None, None),
    ("5 juli", None, "2023-07-05", None),
    ("op 5 juli zei hij", None, "2023-07-05", None),
    ("5 juli en 11 juli 2023", "2023-07-11", "2023-07-05", "2023-07-11"),
    ("", None, None, None),
]


@pytest.mark.parametrize(("text", "abbreviated", "of_the_year", "plain"), _TABLE)
def test_a_day_is_read(
    text: str, abbreviated: str | None, of_the_year: str | None, plain: str | None
) -> None:
    assert dutch_day(text, abbreviations=True) == abbreviated
    assert dutch_day(text, year=2023) == of_the_year
    assert dutch_day(text) == plain


def test_the_fragments_match_what_dutch_day_reads() -> None:
    assert re.fullmatch(DATE, "10 oktober 2018")
    assert not re.fullmatch(DATE, "10 okt. 2018")
    assert re.fullmatch(DATE_ABBREVIATED, "10 okt. 2018")
    assert re.fullmatch(DATE_YEAR_OPTIONAL, "5 juli")
    assert re.fullmatch(DATE_YEAR_OPTIONAL, "5 juli 2023")
    # without groups: a pattern built with one numbers only its own
    found = re.search(rf"van ({DATE}) tot ({DATE})", "van 1 mei 2020 tot 2 juni 2021")
    assert found is not None
    assert [dutch_day(found[1]), dutch_day(found[2])] == ["2020-05-01", "2021-06-02"]


def test_a_day_is_written() -> None:
    assert long_date("2019-12-20") == "20 december 2019"
    assert long_date("1992-01-01T00:00:00") == "1 januari 1992"
    assert long_date("2019-13-01") == ""
    assert long_date(None) == ""


def test_a_day_is_shifted_across_months_and_years() -> None:
    assert day_before("2024-03-01") == "2024-02-29"
    assert day_before("2025-01-01") == "2024-12-31"
    assert shift_day("2023-02-28", 1) == "2023-03-01"
    assert shift_day("2024-12-31", 1) == "2025-01-01"
    assert shift_day("2024-01-10", -14) == "2023-12-27"
