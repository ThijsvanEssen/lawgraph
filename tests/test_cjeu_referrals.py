"""The decision of a Dutch court that referred questions to the Court of Justice, as the
``*A9*`` line CELLAR gives names it, and the decision of the graph it is: the examples are
the referrals ``ops/hvj-nl-gap.sql`` found unanswered on 23 November 2026 next to the
decision of that day whose case number has the same digits."""

from __future__ import annotations

import pytest

from lawgraph.core import cjeu
from lawgraph.core.case_numbers import Referral
from lawgraph.core.court_sources import named_tier
from lawgraph.pipelines.semantic.rechtspraak_referrals import by_case_number

RULING = "ECLI:EU:C:2020:1"


@pytest.mark.parametrize(
    ("named", "candidate"),
    [
        # leading zeros
        ("10/2941", "10/02941"),
        ("12/4408", "12/04408"),
        ("04/4960 DK", "04/04960"),
        # a prefix or a suffix of letters, another separator
        ("02/1399 DK", "02/1399dk"),
        ("05/495 DK", "05/495"),
        ("10/719 WW", "10/719ww-p"),
        ("AWB 21/4536", "awb-21_4536"),
        ("HAA 20/2158", "awb-20_2158"),
        ("AWB 17/2465", "ak_17_2465_tu(002)"),
        ("0086/99 TC", "0086/99"),
        ("HA ZA 13-999", "c/09/450182/haza13-999"),
        # a dot between the thousands, or between the parts
        ("22.246", "22246"),
        ("13.751.400-16", "13/751400-16"),
    ],
)
def test_a_case_number_names_the_same_digits_however_written(
    named: str, candidate: str
) -> None:
    assert Referral(case_numbers=(named,)).names(candidate)


@pytest.mark.parametrize(
    ("named", "candidate"),
    [
        ("10/2941", "10/2942"),
        ("05/495 DK", "05/4950"),
        ("AWB 21/4536", "awb-21_45367"),
        # too few digits to tell by the digits alone
        ("5192", "AWB 02/11 5192"),
        # the same digits, not in that order
        ("13/999", "999/13"),
    ],
)
def test_other_digits_name_another_case(named: str, candidate: str) -> None:
    assert not Referral(case_numbers=(named,)).names(candidate)


@pytest.mark.parametrize(
    ("court", "tier"),
    [
        ("Hoge Raad der Nederlanden", "hoge_raad"),
        ("Raad van State", "raad_van_state"),
        ("Centrale Raad van Beroep", "centrale_raad_van_beroep"),
        (
            "College van Beroep voor het bedrijfsleven",
            "college_van_beroep_bedrijfsleven",
        ),
        ("Gerechtshof te Amsterdam", "gerechtshof"),
        ("Arrondissementsrechtbank te Amsterdam", "rechtbank"),
        ("Rechtbank Den Haag", "rechtbank"),
        ("Kantongerecht te Groningen", "kantongerecht"),
        # no tier of a judgment of today
        ("Raad van Beroep te Amsterdam", None),
        ("Tariefcommissie", None),
        ("Court of Appeal (England & Wales)", None),
    ],
)
def test_the_court_a9_names_has_a_tier(court: str, tier: str | None) -> None:
    assert named_tier(court) == tier


def _row(ecli: str, case_number: str, tier: str | None) -> dict[str, str | None]:
    return {
        "ecli": ecli,
        "date": "2013-04-26",
        "case_number": case_number,
        "tier": tier,
    }


def test_a_decision_of_another_court_is_not_the_referring_one() -> None:
    (referral,) = cjeu.referrals(
        "<p>*A9* Hoge Raad der Nederlanden, 1e kamer, arrest van 26/04/2013 (10/2941)</p>"
    )
    assert referral.tier == "hoge_raad"
    candidates = [
        _row("ECLI:NL:OGEAC:2013:1", "10/2941", "koninkrijksinstantie"),
        _row("ECLI:NL:HR:2013:BZ6793", "10/02941", "hoge_raad"),
        # a court whose tier is not known is not ruled out
        _row("ECLI:NL:XX:2013:1", "10/2941", None),
    ]
    assert by_case_number(RULING, referral, candidates) == [
        "ECLI:NL:HR:2013:BZ6793",
        "ECLI:NL:XX:2013:1",
    ]


def test_an_ecli_without_its_prefix_is_read_in_an_a9_line() -> None:
    national = (
        "<p>*A9* Rechtbank Den Haag, Beslissing van 22/02/2021 (NL:RBDHA:2021:800)</p>"
        "<p>*A9* Centrale Raad van Beroep, Uitspraak van 03/09/2019 (CRVB:2019:2782)</p>"
    )
    assert cjeu.referrals(national) == [
        Referral(eclis=("ECLI:NL:RBDHA:2021:800",)),
        Referral(eclis=("ECLI:NL:CRVB:2019:2782",)),
    ]


def test_an_abbreviated_ecli_of_another_year_is_not_the_referring_decision() -> None:
    # C-610/18: the Centrale Raad referred in 2018; the ECLI is of the Rechtbank in 2016
    line = "<p>*A9* Centrale Raad van Beroep, 20/09/2018 (NL:RBAMS:2016:1638)</p>"
    assert [r.eclis for r in cjeu.referrals(line)] == [()]
