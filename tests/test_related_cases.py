"""The connected cases a judgment's summary names, on sentences from real summaries."""

from __future__ import annotations

import pytest

from lawgraph.core.related_cases import read_related_cases
from lawgraph.pipelines.semantic.rechtspraak_related import match_case_number


def _read(summary: str) -> list[tuple[list[str], list[list[str]]]]:
    return [(r.eclis, r.case_numbers) for r in read_related_cases(summary)]


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        # ECLI:NL:HR:2026:1356
        ("Art. 81.1 RO. Samenhang met 24/01299.", [([], [["24/01299"]])]),
        # ECLI:NL:PHR:2009:BH2815: "nrs." goes on, it ends no sentence
        (
            "Samenhang met nrs. 07/11290 en 08/00909.",
            [([], [["07/11290"], ["08/00909"]])],
        ),
        # ECLI:NL:HR:2025:403: the ECLI as the court abbreviates it
        (
            "Samenhang met HR:2025:404 en HR:2025:405 (zaken van cliënten van klager).",
            [(["ECLI:NL:HR:2025:404", "ECLI:NL:HR:2025:405"], [])],
        ),
        # ECLI:NL:HR:2026:1110: the Hoge Raad's type of case after the number
        (
            "Samenhang met 24/03860 E en met 24/03859 P (niet gepubliceerd; geen schriftuur "
            "ingediend).",
            [([], [["24/03860e", "24/03860"], ["24/03859p", "24/03859"]])],
        ),
        # ECLI:NL:HR:2026:1527: the next sentence is no part of it
        (
            "Samenhang met 25/04731 Bv. Vervolg op HR:2024:1290.",
            [([], [["25/04731bv", "25/04731"]])],
        ),
        # ECLI:NL:HR:2026:1517
        (
            "Zie ook 25/02365, ECLI:NL:HR:2026:1416",
            [(["ECLI:NL:HR:2026:1416"], [["25/02365"]])],
        ),
        # ECLI:NL:RBAMS:2024:7035: two ECLIs without a word between them
        (
            "Zie ook: ECLI:NL:RBAMS:2024:7033 ECLI:NL:RBAMS:2024:7034",
            [(["ECLI:NL:RBAMS:2024:7033", "ECLI:NL:RBAMS:2024:7034"], [])],
        ),
        # ECLI:NL:RBMNE:2015:1838: words before the ECLI
        (
            "Zie ook herstelvonnis d.d. 20 maart 2015 ECLI:NL:RBMNE:2015:1845",
            [(["ECLI:NL:RBMNE:2015:1845"], [])],
        ),
        # a court of appeal's case numbers
        (
            "Samenhang met 200.343.752/01 en 200.344.457/01.",
            [([], [["200.343.752/01"], ["200.344.457/01"]])],
        ),
    ],
)
def test_what_a_sentence_names(summary: str, expected: list) -> None:
    assert _read(summary) == expected


@pytest.mark.parametrize(
    "summary",
    [
        "Zie ook LJN BU3634 en BU3635",  # an old LJN is not read
        "Zie ook ABRS F01.97.0373/P01, dd 10-6-1998 [NA 98/373]. De Afdeling verklaart",
        "Gelet op de samenhang met de zaak van de moeder is het verzoek afgewezen.",
        "",
    ],
)
def test_what_names_no_case(summary: str) -> None:
    assert _read(summary) == []


def test_the_sentence_is_kept_as_written() -> None:
    [related] = read_related_cases("Art. 81.1 RO. Samenhang met  24/01299.")
    assert related.text == "Samenhang met 24/01299."


def test_a_case_number_matches_only_in_the_same_court() -> None:
    rows = {
        "24/01299": [
            {"ecli": "ECLI:NL:HR:2026:1357", "court_code": "HR"},
            {"ecli": "ECLI:NL:PHR:2026:619", "court_code": "PHR"},
        ],
        "24/03860": [{"ecli": "ECLI:NL:HR:2026:1111", "court_code": "HR"}],
    }
    assert match_case_number(["24/01299"], "HR", rows) == ["ECLI:NL:HR:2026:1357"]
    assert match_case_number(["24/01299"], "PHR", rows) == ["ECLI:NL:PHR:2026:619"]
    assert match_case_number(["24/01299"], "GHAMS", rows) == []
    # as written first, then without the type of case
    assert match_case_number(["24/03860e", "24/03860"], "HR", rows) == [
        "ECLI:NL:HR:2026:1111"
    ]
