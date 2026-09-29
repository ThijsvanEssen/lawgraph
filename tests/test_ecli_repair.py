"""ECLIs named in a judgment text: checked for their syntax, repaired where the text shows what
was meant, dropped where it does not (core.ecli)."""

from __future__ import annotations

import pytest

from lawgraph.core.ecli import cited_eclis, is_valid_ecli


@pytest.mark.parametrize(
    "ecli",
    [
        "ECLI:NL:HR:2009:BH2815",
        "ECLI:NL:HR:2019:1278",
        "ECLI:NL:RBAMS:1995:ZC1234",
        "ECLI:NL:GHSCHE:2024:3936",  # well-formed; whether the court exists is not checked
        "ECLI:EU:C:2012:699",
        "ECLI:CE:ECHR:2008:0215JUD002727803",
        "ECLI:DE:BGH:2019:210519UVIZR299.17.0",
        "ECLI:AT:OGH0002:2020:0060OB00077.20X.1125.00",
        "ECLI:BE:CASS:2020:ARR.20201015.1F.6",
    ],
)
def test_a_well_formed_ecli_is_valid(ecli: str) -> None:
    assert is_valid_ecli(ecli)


@pytest.mark.parametrize(
    "ecli",
    [
        "ECLI:NL:HR:2009:BH",  # an LJN without its digits
        "ECLI:NL:HR:2004:AQ808",  # an LJN with three digits
        "ECLI:NL:HR:2013:BZ99521",
        "ECLI:NL:HR:2978:AM4447",  # the year
        "ECLI:NL:HR:1880:1",
        "ECLI:EU:C:2913:164",
        "ECLI:NR:HR:2015:434",  # the country
        "ECLI:HL:HR:2011:BR2086",
        "ECLI:NL:RV5:2021:1468",  # a Dutch court code is letters
        "ECLI:NL:GHAMS:2014:11363.30",
        "ECLI:NL:HR:2018:2374-2375",  # a range is not one ECLI
    ],
)
def test_a_malformed_ecli_is_not_valid(ecli: str) -> None:
    assert not is_valid_ecli(ecli)


def test_the_year_runs_to_the_current_year() -> None:
    assert is_valid_ecli("ECLI:NL:HR:2026:1", this_year=2026)
    assert not is_valid_ecli("ECLI:NL:HR:2027:1", this_year=2026)
    assert is_valid_ecli("ECLI:NL:HR:1900:1", this_year=2026)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # a split LJN is joined
        ("HR 5 juni 2009 (ECLI:NL:HR:2009:BH 2815), en", ["ECLI:NL:HR:2009:BH2815"]),
        ("de Hoge Raad (ECLI:NL:HR:2009:BH:4033). Over", ["ECLI:NL:HR:2009:BH4033"]),
        ("HR 14 april 2000, ECLI:NL:HR:2000:AA55 19). In", ["ECLI:NL:HR:2000:AA5519"]),
        ("(ECLI:NL:RBROT:2012:LJN:BX7991) overwogen", ["ECLI:NL:RBROT:2012:BX7991"]),
        # a split number is joined
        ("HR 8 maart 2019, ECLI:NL:HR:2019: 322. Zie", ["ECLI:NL:HR:2019:322"]),
        # NL and the court swapped back
        ("HR 13 januari 2023, ECLI:HR:NL:2023:26. [5]", ["ECLI:NL:HR:2023:26"]),
        # a range becomes its members
        (
            "HR 18 december 2018, ECLI:NL:HR:2018:2374-2375 in stand",
            ["ECLI:NL:HR:2018:2374", "ECLI:NL:HR:2018:2375"],
        ),
        (
            "(ECLI:NL:CBB:2020:992 - 995) heeft",
            [f"ECLI:NL:CBB:2020:{n}" for n in range(992, 996)],
        ),
        # a word glued to the number is not part of it
        ("23 april 2021, ECLI:NL:HR:2021:661verworpen. De", ["ECLI:NL:HR:2021:661"]),
        (
            "ECLI:NL:HR:2008:BC8231en ECLI:NL:HR:2008:BC8234",
            [
                "ECLI:NL:HR:2008:BC8231",
                "ECLI:NL:HR:2008:BC8234",
            ],
        ),
        ("20 maart 2012, ECLI:NL:HR:2012:BV2954.vgl. ook", ["ECLI:NL:HR:2012:BV2954"]),
        # nor is the next ECLI glued to it
        (
            "6 maart 2020, ECLI:NL:RVS:2020:695ECLI:NL:RVS:2018:3761, onder",
            ["ECLI:NL:RVS:2020:695", "ECLI:NL:RVS:2018:3761"],
        ),
        (
            "HR 1 juli 1998, ECLI:NL:HR:1998:ECLI:NL:HR:1998:ZD1229, NJ",
            ["ECLI:NL:HR:1998:ZD1229"],
        ),
        # a zero or one typed for the letter of an LJN
        (
            "Zie ECLI:NL:HR:2005:A09006 en ECLI:NL:HR:2009:B11943.",
            [
                "ECLI:NL:HR:2005:AO9006",
                "ECLI:NL:HR:2009:BI1943",
            ],
        ),
        (
            "HR 16 december 2005, ECLI:NL:HR:2005:AU8I69, BNB",
            ["ECLI:NL:HR:2005:AU8169"],
        ),
    ],
)
def test_what_the_text_shows_is_repaired(text: str, expected: list[str]) -> None:
    assert cited_eclis(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "HR 4 december 2004, ECLI:NL:HR:2004:AQ808), NJ",
        "HR 13 januari 2011, ECLI:NL:HR:2011:B)7122, NJ",
        "HR 8 december 1978, ECLI:NL:HR:2978:AM4447. Vgl.",
        "(ECLI:NR:HR:2015:434) blijkt",
        "ECLI:NL:HR:2013:BZ99521, overwoog",
        "(ECLI:NL:GHAMS:2014:11363.30). Deze",
        "ECLI:HR:NL:2011:BO05046.",
    ],
)
def test_what_cannot_be_repaired_is_dropped(text: str) -> None:
    assert cited_eclis(text) == []


def test_the_digits_of_an_ljn_are_joined_only_to_complete_it() -> None:
    # a number is complete: the figure after it is something else
    assert cited_eclis("ECLI:NL:HR:2019:1278 2019") == ["ECLI:NL:HR:2019:1278"]
    assert cited_eclis("ECLI:NL:HR:2009:BH2815 12") == ["ECLI:NL:HR:2009:BH2815"]
    # a descending or very long span is no range
    assert cited_eclis("ECLI:NL:HR:2018:2375-2374") == []
    assert cited_eclis("ECLI:NL:HR:2018:1-500") == []


def test_well_formed_eclis_pass_unchanged_once_each() -> None:
    text = (
        "Zie ECLI:NL:HR:2005:AU1234, ecli:nl:hr:2005:au1234 en "
        "ECLI:CE:ECHR:2019:0101JUD001234510; ECLI:EU:C:2021:7 - echter"
    )
    assert cited_eclis(text) == [
        "ECLI:NL:HR:2005:AU1234",
        "ECLI:CE:ECHR:2019:0101JUD001234510",
        "ECLI:EU:C:2021:7",
    ]
    assert cited_eclis(None) == [] and cited_eclis("") == []
