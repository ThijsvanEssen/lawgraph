"""The cabinet pages of Rijksoverheid: dates, holder lines, headings, facts and resignations."""

from __future__ import annotations

from pathlib import Path

import pytest

from lawgraph.clients.rijksoverheid import cabinet_slugs
from lawgraph.core.cabinet_posts import heading_parts, person_key, seat_of
from lawgraph.core.rijksoverheid import (
    SECTION_MINISTERS,
    SECTION_STATE_SECRETARIES,
    parse_date,
    parse_holder,
    parse_page,
    split_name,
)

PAGES = Path(__file__).parent / "fixtures" / "rijksoverheid"


def _page(slug: str) -> dict:
    return parse_page((PAGES / f"{slug}.html").read_text())


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("3 juni 2025", "2025-06-03"),
        ("15 sept. 1947", "1947-09-15"),
        ("8 sep.1977", "1977-09-08"),
        ("1 febr. 1972", "1972-02-01"),
        ("24 mrt 2000", "2000-03-24"),
        ("27 janauri 2017", None),  # the source's typo is no day
    ],
)
def test_a_day_is_read_in_every_way_the_pages_write_it(text: str, day: str) -> None:
    assert parse_date(text) == day


def _one(line: str) -> dict:
    holder = parse_holder(line)
    assert holder is not None
    return holder


def test_a_holder_line_gives_name_party_and_period() -> None:
    hermans = _one("Drs. S.Th.M. (Sophie) Hermans (VVD), 3 juni 2025 - 19 juni 2025")
    assert (hermans["name"], hermans["party"]) == (
        "Drs. S.Th.M. (Sophie) Hermans",
        "VVD",
    )
    assert hermans["periods"] == [
        {"from_date": "2025-06-03", "to_date": "2025-06-19", "ended": None}
    ]
    assert not hermans["acting"]
    moes = _one("G. (Gouke) Moes (BBB), vanaf 5 september 2025")
    assert moes["periods"][0]["from_date"] == "2025-09-05"
    assert moes["periods"][0]["to_date"] is None


@pytest.mark.parametrize(
    ("line", "start", "end"),
    [
        (
            "dr. I. Samkalden (PvdA), a.i., 31 aug.-5 sep. 1966",
            "1966-08-31",
            "1966-09-05",
        ),
        ("mr. V.G.M. Marijnen (KVP), a.i., 3-17 juli 1961", "1961-07-03", "1961-07-17"),
        (
            "mr. J.H. van Maarseveen (KVP), a.i., 15 mei-10 juli 1950",
            "1950-05-15",
            "1950-07-10",
        ),
        ("J. Smallenbroek (ARP), afgetreden 31 aug. 1966", None, "1966-08-31"),
        ("Dr. B.R. Bot, 3 december 2003", "2003-12-03", None),
        ("Mr. M.C. van der Laan (D66) afgetreden 3 juli 2006", None, "2006-07-03"),
        (
            "J.J.F. Borghouts (KVP), 13 juli 1965 overleden 5 feb. 1966",
            "1965-07-13",
            "1966-02-05",
        ),
        (
            "Drs. S.P.R.A. (Steven) van Weyenberg (D66), sinds10 augustus 2021",
            "2021-08-10",
            None,
        ),
    ],
)
def test_every_way_a_line_gives_its_period(line: str, start, end) -> None:
    (period,) = _one(line)["periods"]
    assert (period["from_date"], period["to_date"]) == (start, end)


def test_a_line_with_two_periods_gives_both() -> None:
    knops = _one(
        "R.W. (Raymond) Knops (CDA), 26 oktober 2017 - 1 november 2019 en sinds 14 april 2020"
    )
    assert [(p["from_date"], p["to_date"]) for p in knops["periods"]] == [
        ("2017-10-26", "2019-11-01"),
        ("2020-04-14", None),
    ]


def test_a_line_says_acting_definitive_absent_and_who_took_over() -> None:
    schokking = _one(
        "mr. W.F. Schokking (CHU), a.i., definitief 14 mei 1949, afgetreden 16 okt. 1950"
    )
    assert schokking["acting"] and schokking["until_acting"] == "1949-05-14"
    assert schokking["periods"][0]["to_date"] == "1950-10-16"
    burg = _one(
        "E. (Eric) van der Burg (VVD), tijdelijk afwezig van 30 oktober 2023 - 23 november 2023"
    )
    assert burg["absent"] == ("2023-10-30", "2023-11-23")
    assert burg["periods"][0]["from_date"] is None
    bomhoff = _one(
        "Dr. E.J. Bomhoff (LPF), afgetreden 16 oktober 2002, beheer portefeuille overgenomen "
        "door de minister van SZW"
    )
    assert bomhoff["taken_over_by"] == "minister van SZW"
    assert _one(
        "M.F. (Fleur) Agema MA (PVV), 2 juli 2024 - 3 juni 2025. Ook viceminister-president"
    )["also_deputy"]
    boerma = _one(
        "C.J. (Hanneke) Boerma (NSC), staatssecretaris Buitenlandse Handel, "
        "19 juni 2025 - 22 augustus 2025"
    )
    assert boerma["portfolio"] == "staatssecretaris Buitenlandse Handel"


def test_a_party_and_its_absence() -> None:
    assert (
        _one("Dr. mr. Th.H.D. (Teun) Struycken (op voordracht van NSC; partijloos)")[
            "party"
        ]
        == "partijloos"
    )
    assert _one("L. de Graaf CDA) afgetreden 1 juni 1987")["party"] == "CDA"
    assert _one("Dr. B.R. Bot (CDA)")["party"] == "CDA"  # a short surname is no initial
    assert parse_holder("Deze taken werden vervolgens opgedragen aan:") is None
    assert parse_holder("(belast met de hulp aan ontwikkelingslanden)") is None


def test_a_name_splits_into_initials_first_name_and_surname() -> None:
    assert split_name("Drs. S.Th.M. (Sophie) Hermans") == {
        "initials": "S.Th.M.",
        "letters": "stm",
        "first_name": "Sophie",
        "surname": "Hermans",
    }
    assert split_name("mw. D.IJ.W. de Graaff-Nauta")["letters"] == "dijw"
    assert split_name("H.G.J Kamp")["initials"] == "H.G.J."
    assert split_name("dr. B de Vries")["surname"] == "de Vries"
    assert split_name("drs. L..J.M. van Son")["initials"] == "L.J.M."
    assert person_key("Drs. S.Th.M. (Sophie) Hermans") == "stm hermans"


def test_a_heading_names_its_posts() -> None:
    parts = heading_parts(
        "Minister-president, minister van Algemene Zaken", SECTION_MINISTERS
    )
    assert [p["function"] for p in parts] == [
        "Minister-president",
        "minister van Algemene Zaken",
    ]
    beel = heading_parts(
        "Minister-president, tot 15 sept. 1947 tevens minister van Binnenlandse Zaken en "
        "vanaf 11 okt. 1947 tevens minister van Algemene Zaken",
        SECTION_MINISTERS,
    )
    assert [(p["function"], p["from_date"], p["to_date"]) for p in beel] == [
        ("Minister-president", None, None),
        ("minister van Binnenlandse Zaken", None, "1947-09-15"),
        ("minister van Algemene Zaken", "1947-10-11", None),
    ]
    # a later name of the same post
    (renamed,) = heading_parts(
        "Minister van Uniezaken en Overzeese Rijksdelen, vanaf 1 jan. 1953 minister van "
        "Overzeese Rijksdelen",
        SECTION_MINISTERS,
    )
    assert renamed["also_named"] == ["minister van Overzeese Rijksdelen"]
    (charged,) = heading_parts(
        "Minister zonder Portefeuille (belast met de hulp aan ontwikkelingslanden)",
        SECTION_MINISTERS,
    )
    assert charged["portfolio"] == "hulp aan ontwikkelingslanden"
    (state,) = heading_parts("Buitenlandse Zaken", SECTION_STATE_SECRETARIES)
    assert state["function"] == "staatssecretaris van Buitenlandse Zaken"


@pytest.mark.parametrize(
    ("function", "seat", "named"),
    [
        ("Minister-president", "az/minister-president", True),
        ("minister van Algemene Zaken", "az/minister-president", True),
        ("Minister van Infrastructuur en Waterstaat", "ienw/minister", True),
        ("Minister van Verkeer en Waterstaat", "ienw/minister", True),
        (
            "Minister van Werk en Participatie",
            "szw/minister/werk-en-participatie",
            True,
        ),
        (
            "Minister voor Buitenlandse Handel en Ontwikkelingshulp",
            "bz/minister_zonder_portefeuille/buitenlandse-handel-en-ontwikkelingshulp",
            True,
        ),
        ("Minister zonder Portefeuille", "-/minister_zonder_portefeuille", False),
        ("staatssecretaris van Financiën", "fin/staatssecretaris", False),
        (
            "Staatssecretaris Rechtsbescherming",
            "jenv/staatssecretaris/rechtsbescherming",
            True,
        ),
        ("Vice-minister-president", "viceminister-president", True),
    ],
)
def test_a_post_sits_in_a_seat(function: str, seat: str, named: bool) -> None:
    found = seat_of(function, None, None, "2025-07-01")
    assert (found["seat"], found["named"]) == (seat, named)


def test_the_index_links_each_cabinet_once() -> None:
    index = (
        '<a href="/regering/over-de-regering/kabinetten-sinds-1945/kabinet-schoof">'
        '<a href="/regering/over-de-regering/kabinetten-sinds-1945/kabinet-jetten">'
        '<a href="/regering/over-de-regering/kabinetten-sinds-1945/kabinet-schoof">'
    )
    assert cabinet_slugs(index) == ["kabinet-schoof", "kabinet-jetten"]


def test_the_schoof_page() -> None:
    page = _page("kabinet-schoof")
    assert page["name"] == "Kabinet-Schoof (2024-2026)"
    assert page["intro_from"] == "2024-07-02"
    facts = {f["label"]: f["date"] for f in page["facts"]}
    assert facts["Beëdiging kabinet"] == "2024-07-02"
    assert facts["Tweede Kamerverkiezing"] == "2023-11-22"
    assert [r["date"] for r in page["resignations"]] == ["2025-06-03", "2025-08-22"]
    ienw = next(
        s for s in page["seats"] if s["heading"].startswith("Minister van Infra")
    )
    assert len(ienw["lines"]) == 3


def test_a_resignation_after_the_elections_gives_no_day() -> None:
    # "Na de Tweede Kamerverkiezingen van 22 november 2006 bood het kabinet zijn ontslag aan."
    assert _page("kabinet-balkenende-iii")["resignations"] == []


def test_the_items_after_a_temporary_arrangement_stand_in_for_its_period() -> None:
    temporary = [s for s in _page("kabinet-lubbers-ii")["seats"] if s["temporary"]]
    assert {s["temporary"]["from_date"] for s in temporary} == {"1987-02-03"}
    assert {s["temporary"]["to_date"] for s in temporary} == {"1987-05-06"}
