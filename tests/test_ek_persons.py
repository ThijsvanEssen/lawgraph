"""The page of a member of the Eerste Kamer: their name, birth and the factions they sat in,
from when until when, as the page says it (real pages)."""

from __future__ import annotations

from pathlib import Path

from lawgraph.core.ek_persons import (
    Period,
    bare_name,
    faction_name,
    match_member,
    person_page,
)

EK = Path(__file__).parent / "fixtures" / "eerstekamer"


def _page(slug: str):
    found = person_page((EK / f"persoon_{slug}.html").read_text("utf-8"))
    assert found is not None
    return found


def test_a_sitting_member_since_a_day_with_their_birth_date() -> None:
    page = _page("mr_b_o_dittrich_d66")
    assert page.name == "Mr. B.O. Dittrich (D66)"
    assert (page.birth_year, page.birth_date) == ("1955", "1955-07-21")
    assert page.periods == [Period("D66", "2019-06-11", None)]


def test_a_member_who_left_their_faction_and_the_kamer() -> None:
    """The current period first, then "Eerder was hij van … tot …"; each ends the day
    before the page's "tot", the day the next began."""
    otten = _page("mr_drs_h_otten_fractie_otten")
    assert otten.birth_date is None and otten.birth_year == "1967"
    assert otten.periods == [
        Period("Fractie-Otten", "2019-07-28", "2023-06-12"),
        Period("FVD", "2019-06-11", "2019-07-27"),
    ]
    duthler = _page("mr_dr_a_w_duthler_fractie_duthler")
    assert duthler.periods == [
        Period("Fractie-Duthler", "2019-04-26", "2019-06-10"),
        Period("VVD", "2007-06-12", "2019-04-25"),
    ]


def test_a_faction_as_the_page_names_it() -> None:
    assert faction_name("D66-fractie") == "D66"
    assert faction_name("Fractie-Otten") == "Fractie-Otten"


def test_a_page_of_no_member() -> None:
    assert (
        person_page("<html><title>Niet gevonden</title><body>Nee</body></html>") is None
    )


_BORN = [
    {"key": "m1", "family_name": "Dittrich", "birth_date": "1955-07-21"},
    {"key": "m2", "family_name": "Jansen", "birth_date": "1955-07-21"},
    {"key": "m3", "family_name": "Dittrich", "birth_date": "1960-01-01"},
]


def test_a_member_of_the_tweede_kamer_born_that_day_whose_surname_ends_the_name() -> (
    None
):
    assert match_member("Mr. B.O. Dittrich", "1955-07-21", _BORN) == "m1"
    assert match_member("Mr. B.O. Dittrich (D66)", "1955-07-21", _BORN) == "m1"
    assert match_member("G.J. Jansen (PVV)", "1955-07-21", _BORN) == "m2"


def test_no_member_without_a_birth_date_a_surname_or_one_candidate() -> None:
    assert match_member("Mr. B.O. Dittrich", None, _BORN) is None
    assert match_member("Mr. B.O. Dittrich", "1970-01-01", _BORN) is None
    assert match_member("A. de Vries (PVV)", "1955-07-21", _BORN) is None
    two = [*_BORN, {"key": "m4", "family_name": "Dittrich", "birth_date": "1955-07-21"}]
    assert match_member("Mr. B.O. Dittrich (D66)", "1955-07-21", two) is None
    nameless = [{"key": "m5", "family_name": None, "birth_date": "1955-07-21"}]
    assert match_member("Dittrich", "1955-07-21", nameless) is None


def test_the_bare_name_leaves_the_faction_out() -> None:
    assert bare_name("Mr. B.O. Dittrich (D66)") == "Mr. B.O. Dittrich"
    assert bare_name("Mr. B.O. Dittrich") == "Mr. B.O. Dittrich"
