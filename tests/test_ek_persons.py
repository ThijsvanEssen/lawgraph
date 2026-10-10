"""The page of a member of the Eerste Kamer: their name, birth and the factions they sat in,
from when until when, as the page says it (real pages)."""

from __future__ import annotations

from pathlib import Path

from lawgraph.core.ek_persons import Period, faction_name, person_page

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
