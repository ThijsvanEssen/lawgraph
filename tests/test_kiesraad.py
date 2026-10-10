"""The result of an election of the Eerste Kamer from the Kiesraad's databank page."""

from __future__ import annotations

from pathlib import Path

import pytest

from lawgraph.core.kiesraad import EK_ELECTIONS, list_names, parse_ek_result

FIXTURES = Path(__file__).parent / "fixtures" / "kiesraad"


@pytest.mark.parametrize("code", EK_ELECTIONS)
def test_every_election_fills_the_75_seats(code: str) -> None:
    result = parse_ek_result((FIXTURES / f"{code}.html").read_text("utf-8"))
    assert result is not None
    assert result.code == code
    assert result.date == f"{code[2:6]}-{code[6:8]}-{code[8:10]}"
    assert sum(result.seats.values()) == 75


def test_the_seats_of_2023_and_2007() -> None:
    of_2023 = parse_ek_result((FIXTURES / "EK20230530.html").read_text("utf-8"))
    assert of_2023 is not None
    assert of_2023.seats["BBB"] == 16
    assert of_2023.seats["Partij van de Arbeid (P.v.d.A.)"] == 7
    assert of_2023.seats["GROENLINKS"] == 7
    of_2007 = parse_ek_result((FIXTURES / "EK20070529.html").read_text("utf-8"))
    assert of_2007 is not None
    assert (of_2007.seats["CDA"], of_2007.seats["VVD"], of_2007.seats["PvdA"]) == (
        21,
        14,
        14,
    )


def test_a_page_without_its_data() -> None:
    assert parse_ek_result("<html><body>Niet gevonden</body></html>") is None


def test_the_names_a_list_is_matched_by() -> None:
    assert list_names("Partij van de Arbeid (P.v.d.A.)") == {
        "PARTIJ VAN DE ARBEID (P.V.D.A.)",
        "PARTIJ VAN DE ARBEID",
        "P.V.D.A.",
        "PVDA",
    }
    assert list_names("BBB") == {"BBB"}
