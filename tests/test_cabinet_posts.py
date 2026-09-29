"""The rules of a seat and the phases of a cabinet, on every cabinet and on the cases that
made them.

The pages are the Rijksoverheid pages of every cabinet since 1945 (``fixtures/rijksoverheid``,
read on 25 September 2026).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import pytest

from lawgraph.core.cabinet_checks import violations
from lawgraph.core.cabinet_phases import PHASE_KINDS
from lawgraph.core.cabinet_posts import (
    ACTING_HELD_OTHER_SEAT,
    ACTING_SOURCE,
    BASIS_AI,
    CORRECTED_BY_PREDECESSOR,
    CORRECTED_BY_SUCCESSOR,
    SEAT_DEPUTY,
    cabinet_posts,
    seat_gaps,
)
from lawgraph.core.cabinet_sources import build_cabinets
from lawgraph.core.rijksoverheid import SECTION_MINISTERS, parse_page

FIXTURES = Path(__file__).parent / "fixtures"


@cache
def _cabinets() -> tuple[dict[str, Any], ...]:
    pages = [
        {
            "slug": path.stem,
            "url": f"https://www.rijksoverheid.nl/.../{path.stem}",
            "read_on": "2026-09-25",
            "page": parse_page(path.read_text()),
        }
        for path in sorted((FIXTURES / "rijksoverheid").glob("*.html"))
    ]
    return tuple(build_cabinets(pages, lambda text: {"short": text, "faction": None}))


def _cabinet(key: str) -> dict[str, Any]:
    return next(c for c in _cabinets() if c["key"] == key)


def _held(key: str, seat: str) -> list[tuple[str, str, str | None, bool]]:
    return [
        (p["person"], p["from_date"], p["to_date"], p["acting"])
        for p in sorted(_cabinet(key)["posts"], key=lambda p: p["from_date"])
        if p["seat"] == seat
    ]


# ── Every cabinet ────────────────────────────────────────────────────────────


def test_every_cabinet_is_there_once_and_follows_the_one_before() -> None:
    cabinets = _cabinets()
    # 32 pages since 1945: Rijksoverheid describes Biesheuvel I and II as one cabinet
    assert len(cabinets) == 32
    assert len({c["key"] for c in cabinets}) == len(cabinets)
    for before, after in zip(cabinets, cabinets[1:], strict=False):
        assert after["previous"] == before["key"]
        assert before["to_date"] == after["from_date"], after["key"]
    assert [c["key"] for c in cabinets if c["to_date"] is None] == ["jetten"]


@pytest.mark.parametrize("cabinet", _cabinets(), ids=lambda c: c["key"])
def test_every_cabinet_meets_the_rules(cabinet: dict[str, Any]) -> None:
    assert violations(cabinet, cabinet["posts"]) == []


def test_every_cabinet_has_posts_and_phases() -> None:
    for cabinet in _cabinets():
        assert cabinet["posts"] and cabinet["phases"], cabinet["key"]
        assert all(p["kind"] in (*PHASE_KINDS, None) for p in cabinet["phases"])
    assert _cabinet("schermerhorn_drees")["previous"] is None


def test_every_post_names_a_holder_a_seat_and_mostly_a_party() -> None:
    posts = [p for c in _cabinets() for p in c["posts"]]
    assert all(p["person"] and p["seat"] for p in posts)
    assert sum(1 for p in posts if p["party"]) / len(posts) > 0.98


# ── Kabinet-Schoof (the faults that were found) ───────────────────────────────


def test_schoof_stand_ins_end_where_the_next_holder_begins() -> None:
    assert _held("schoof", "ienw/minister") == [
        ("b madlener", "2024-07-02", "2025-06-03", False),
        ("stm hermans", "2025-06-03", "2025-06-19", True),
        ("r tieman", "2025-06-19", "2026-02-23", False),
    ]
    assert _held("schoof", "ocw/minister") == [
        ("eew bruins", "2024-07-02", "2025-08-22", False),
        ("stm hermans", "2025-08-22", "2025-09-05", True),
        ("g moes", "2025-09-05", "2026-02-23", False),
    ]
    hermans = [
        p
        for p in _cabinet("schoof")["posts"]
        if p["person"] == "stm hermans" and p["acting"]
    ]
    assert {
        (p["acting_reason"], p["acting_basis"], p["acting_other_seat"]["function"])
        for p in hermans
    } == {(ACTING_HELD_OTHER_SEAT, None, "Minister van Klimaat en Groene Groei")}


def test_schoof_phases() -> None:
    schoof = _cabinet("schoof")
    assert [(p["kind"], p["from_date"], p["to_date"]) for p in schoof["phases"]] == [
        ("formatie", "2023-11-22", "2024-07-02"),
        ("in_functie", "2024-07-02", "2025-06-03"),
        ("demissionair", "2025-06-03", "2025-08-22"),
        ("dubbel_demissionair", "2025-08-22", "2026-02-23"),
    ]
    assert schoof["demissionary_from"] == "2025-06-03"
    assert [p["short"] for p in schoof["parties"]] == ["PVV", "VVD", "NSC", "BBB"]


def test_schoof_keeps_the_overlap_the_source_gives() -> None:
    # Rijksoverheid lists Keijzer as minister voor Asiel en Migratie from 19 June 2025,
    # while Van Hijum held that post until 22 August 2025.
    seat = "-/minister_zonder_portefeuille/asiel-en-migratie"
    overlapping = {
        p["person"]: p["overlaps_with"]
        for p in _cabinet("schoof")["posts"]
        if p["seat"] == seat
    }
    assert overlapping == {
        "mcg keijzer": ["yj van hijum"],
        "yj van hijum": ["mcg keijzer"],
    }


def test_the_prime_minister_is_one_post_under_two_names() -> None:
    (schoof,) = [
        p for p in _cabinet("schoof")["posts"] if p["seat"] == "az/minister-president"
    ]
    assert schoof["also_named"] == ["minister van Algemene Zaken"]


# ── Hand checks over the periods ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "phases"),
    [
        (
            "drees_iii",
            [
                ("formatie", "1956-06-13"),
                ("in_functie", "1956-10-13"),
                ("demissionair", "1958-12-12"),
            ],
        ),
        (
            "de_quay",
            [
                ("formatie", "1959-03-12"),
                ("in_functie", "1959-05-19"),
                ("demissionair", "1960-12-23"),
                ("missionair", "1961-01-02"),
                (None, "1963-05-15"),
            ],
        ),
        (
            "den_uyl",
            [
                ("formatie", "1972-11-29"),
                ("in_functie", "1973-05-11"),
                ("demissionair", "1977-03-22"),
            ],
        ),
        (
            "lubbers_iii",
            [
                ("formatie", "1989-09-06"),
                ("in_functie", "1989-11-07"),
                (None, "1994-05-03"),
            ],
        ),
        (
            "kok_ii",
            [
                ("formatie", "1998-05-06"),
                ("in_functie", "1998-08-03"),
                ("demissionair", "1999-05-19"),
                ("missionair", "1999-06-08"),
                ("demissionair", "2002-04-16"),
            ],
        ),
        (
            "rutte_verhagen",
            [
                ("formatie", "2010-06-09"),
                ("in_functie", "2010-10-14"),
                ("demissionair", "2012-04-23"),
            ],
        ),
        ("jetten", [("formatie", "2025-10-29"), ("in_functie", "2026-02-23")]),
    ],
)
def test_the_phases_of_cabinets_from_every_period(key: str, phases: list) -> None:
    assert [(p["kind"], p["from_date"]) for p in _cabinet(key)["phases"]] == phases


def test_an_ai_line_is_a_stand_in_between_two_holders() -> None:
    # Cals: Smallenbroek resigned 31 Aug 1966, Samkalden a.i., Verdam from 5 Sep 1966
    assert _held("cals", "biza/minister") == [
        ("j smallenbroek", "1965-04-14", "1966-08-31", False),
        ("i samkalden", "1966-08-31", "1966-09-05", True),
        ("pj verdam", "1966-09-05", "1966-11-22", False),
    ]
    (samkalden,) = [
        p
        for p in _cabinet("cals")["posts"]
        if p["person"] == "i samkalden" and p["acting"]
    ]
    assert (samkalden["acting_reason"], samkalden["acting_basis"]) == (
        ACTING_SOURCE,
        BASIS_AI,
    )


def test_a_holder_listed_after_one_who_resigned_starts_when_that_one_left() -> None:
    # Biesheuvel: De Brauw resigned 20 July 1972; "Deze taken werden vervolgens opgedragen
    # aan: mr. C. van Veen" without a day
    seat = "-/minister_zonder_portefeuille/wetenschapsbeleid-en-het-wetenschappelijk-onderwijs"
    (van_veen,) = [
        p
        for p in _cabinet("biesheuvel")["posts"]
        if p["seat"] == seat and p["person"] == "c van veen"
    ]
    assert van_veen["from_date"] == "1972-07-20"
    assert van_veen["from_date_source"] is None
    assert CORRECTED_BY_PREDECESSOR in van_veen["corrected"]


def test_a_portfolio_taken_over_is_a_stand_in_until_the_next_holder() -> None:
    # Balkenende I: Bomhoff (VWS) resigned 16 Oct 2002, "beheer portefeuille overgenomen door
    # de minister van SZW" (De Geus)
    vws = _held("balkenende_i", "vws/minister")
    assert vws[0][:3] == ("ej bomhoff", "2002-07-22", "2002-10-16")
    assert vws[1] == ("aj de geus", "2002-10-16", "2003-05-27", True)


def test_seats_the_source_does_not_name_are_lanes_without_changed_dates() -> None:
    # Balkenende I: two staatssecretarissen of Buitenlandse Zaken, no portfolios
    seats = {
        p["seat"]
        for p in _cabinet("balkenende_i")["posts"]
        if p["seat"].startswith("bz/staats")
    }
    assert seats == {"bz/staatssecretaris", "bz/staatssecretaris#2"}


def test_seat_gaps_are_longer_than_two_weeks() -> None:
    gaps = seat_gaps(_cabinet("de_quay")["posts"])
    assert {
        "seat": "def/minister",
        "from_date": "1959-08-01",
        "to_date": "1959-09-07",
    } in gaps


# ── The rules on their own ───────────────────────────────────────────────────


def _page(*seats: tuple[str, list[str]]) -> dict[str, Any]:
    return {
        "seats": [
            {
                "section": SECTION_MINISTERS,
                "heading": h,
                "lines": lines,
                "notes": [],
                "temporary": None,
            }
            for h, lines in seats
        ]
    }


CABINET = {"from_date": "2020-01-01", "to_date": "2022-01-01"}


def test_an_end_the_source_leaves_out_is_the_start_of_the_next_holder() -> None:
    posts = cabinet_posts(
        _page(
            (
                "Minister van Financiën",
                ["A.B. Eerst (X)", "C.D. Later (X), vanaf 1 juni 2021"],
            )
        ),
        CABINET,
    )
    first, later = sorted(posts, key=lambda p: p["from_date"])
    assert (first["to_date"], first["to_date_source"]) == ("2021-06-01", None)
    assert first["corrected"] == [CORRECTED_BY_SUCCESSOR]
    assert later["to_date"] == "2022-01-01"


def test_two_holders_of_one_named_seat_with_given_days_overlap_openly() -> None:
    posts = cabinet_posts(
        _page(
            (
                "Minister van Financiën",
                [
                    "A.B. Eerst (X), 1 januari 2020 - 1 juni 2021",
                    "C.D. Later (X), 1 maart 2021 - 1 januari 2022",
                ],
            )
        ),
        CABINET,
    )
    assert {p["person"]: p["overlaps_with"] for p in posts} == {
        "ab eerst": ["cd later"],
        "cd later": ["ab eerst"],
    }


def test_two_listings_of_one_seat_on_the_same_days_are_one_post() -> None:
    posts = cabinet_posts(
        _page(
            ("Minister-president, minister van Algemene Zaken", ["A.B. Premier (X)"])
        ),
        CABINET,
    )
    assert len(posts) == 1


def test_a_deputy_shares_one_seat_with_every_other_deputy() -> None:
    posts = cabinet_posts(
        _page(
            ("Vice-minister-president en minister van Financiën", ["A.B. Een (X)"]),
            ("Minister van Defensie", ["C.D. Twee (Y). Ook viceminister-president"]),
        ),
        CABINET,
    )
    deputies = [p for p in posts if p["seat"] == SEAT_DEPUTY]
    assert {p["person"] for p in deputies} == {"ab een", "cd twee"}
    assert all(not p["overlaps_with"] for p in deputies)


def test_a_holder_who_held_another_seat_throughout_stood_in() -> None:
    posts = cabinet_posts(
        _page(
            ("Minister van Financiën", ["A.B. Vast (X)"]),
            (
                "Minister van Defensie",
                [
                    "C.D. Eerst (Y), 1 januari 2020 - 1 maart 2021",
                    "A.B. Vast (X), 1 maart 2021 - 20 maart 2021",
                    "E.F. Later (Y), vanaf 20 maart 2021",
                ],
            ),
        ),
        CABINET,
    )
    (standing,) = [
        p for p in posts if p["seat"] == "def/minister" and p["person"] == "ab vast"
    ]
    assert standing["acting"] and standing["acting_reason"] == ACTING_HELD_OTHER_SEAT
    # whoever follows no one, or leaves no one to follow, did not stand in
    assert not any(p["acting"] for p in posts if p["person"] != "ab vast")


def test_without_pages_there_are_no_cabinets() -> None:
    assert build_cabinets([], lambda text: None) == []


def test_the_holders_of_one_heading_who_follow_one_another_hold_one_seat() -> None:
    # Schoof: the page lists Idsinga under "Staatssecretaris Fiscaliteit, Belastingdienst en
    # Douane", his line naming the post as it was then
    fiscaliteit = _held(
        "schoof", "-/staatssecretaris/fiscaliteit-belastingdienst-en-douane"
    )
    assert [p[0] for p in fiscaliteit] == [
        "fl idsinga",
        "t van oostenbruggen",
        "ehj heijnen",
    ]
    (idsinga,) = [p for p in _cabinet("schoof")["posts"] if p["person"] == "fl idsinga"]
    assert idsinga["also_named"] == ["staatssecretaris Fiscaliteit en Belastingdienst"]
    seats = {p["seat"] for p in _cabinet("schoof")["posts"]}
    assert "-/staatssecretaris/fiscaliteit-en-belastingdienst" not in seats
    assert "-/staatssecretaris/toeslagen-en-douane" not in seats
    assert "-/staatssecretaris/buitenlandse-handel" not in seats


def test_the_holders_of_one_heading_at_the_same_time_hold_seats_of_their_own() -> None:
    # Schoof: Szabó and Van Marum, both "Staatssecretaris van Binnenlandse Zaken en
    # Koninkrijksrelaties", from the same day
    seats = {
        p["seat"]
        for p in _cabinet("schoof")["posts"]
        if p["person"] in ("fz szabo", "e van marum")
    }
    assert {
        "bzk/staatssecretaris/digitalisering-en-koninkrijksrelaties",
        "bzk/staatssecretaris/herstel-groningen",
    } <= seats


def test_a_ministry_renamed_during_the_cabinet_keeps_its_seat_in_one_place() -> None:
    # Rutte-Asscher: the state secretary of Economische Zaken, Landbouw en Innovatie, named
    # Economische Zaken from 1 January 2013 (TOOI); one seat, by its later name
    held = [
        (p["person"], p["from_date"], p["ministry"])
        for p in _cabinet("rutte_asscher")["posts"]
        if p["seat"] == "ez/staatssecretaris"
    ]
    assert [(person, ministry) for person, _, ministry in held] == [
        ("c verdaas", "eli"),
        ("sam dijksma", "eli"),
        ("mhp van dam", "ez"),
    ]
    # Kamp, minister for the whole cabinet: one post from before the new name
    (kamp,) = [
        p for p in _cabinet("rutte_asscher")["posts"] if p["person"] == "hgj kamp"
    ]
    assert (kamp["seat"], kamp["ministry"]) == ("ez/minister", "eli")
    assert not any(
        p["seat"].startswith("eli/") for p in _cabinet("rutte_asscher")["posts"]
    )
