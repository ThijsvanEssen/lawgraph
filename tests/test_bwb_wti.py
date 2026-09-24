"""WTI parsing and the short-title rule, on real ``<algemene-informatie>`` XML."""

from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

import pytest

from lawgraph.core.bwb_wti import (
    choose_short_titles,
    extract_general_info,
    parse_abbreviations,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# The first bytes of the Wetboek van Strafrecht WTI, cut off inside the next element.
SR_HEAD = (FIXTURES / "bwb_wti_sr_head.xml").read_text()
# The element as it is stored, of Burgerlijk Wetboek Boek 1.
BW1_GENERAL = (FIXTURES / "bwb_wti_bw1_general.xml").read_text()


def test_extracts_the_complete_element_from_a_truncated_file() -> None:
    general_info = extract_general_info(SR_HEAD)

    assert general_info is not None
    assert general_info.startswith("<algemene-informatie ")
    assert general_info.endswith("</algemene-informatie>")
    ET.fromstring(general_info)  # well-formed on its own


def test_an_incomplete_or_missing_element_yields_nothing() -> None:
    cut = SR_HEAD[: SR_HEAD.index("</algemene-informatie>")]

    assert extract_general_info(cut) is None
    assert extract_general_info("<wetstechnische-informatie/>") is None


def test_abbreviations_come_in_source_order() -> None:
    general_info = extract_general_info(SR_HEAD)
    assert general_info is not None

    assert parse_abbreviations(general_info) == ["Sr", "WvS", "WvSr"]
    assert parse_abbreviations(BW1_GENERAL) == ["BW", "BW Boek 1", "BW1"]


def test_case_variants_count_once_and_absence_is_an_empty_list() -> None:
    variant = BW1_GENERAL.replace("BW Boek 1", "bw").replace(">BW1<", "> <")
    without = BW1_GENERAL.replace("afkorting", "x")

    assert parse_abbreviations(variant) == ["BW"]
    assert parse_abbreviations(without) == []


def test_broken_xml_raises() -> None:
    with pytest.raises(ET.ParseError):
        parse_abbreviations("<algemene-informatie>")


def test_the_shortest_abbreviation_wins() -> None:
    chosen = choose_short_titles(
        {
            "BWBR0001854": ["Sr", "WvS", "WvSr"],
            "BWBR0006622": ["WVW", "WVW 1994"],
            "BWBR0005537": ["Awb"],
            "BWBR0040179": [],
        }
    )

    assert chosen == {
        "BWBR0001854": "Sr",
        "BWBR0006622": "WVW",
        "BWBR0005537": "Awb",
        "BWBR0040179": None,
    }


def test_equal_lengths_keep_the_source_order() -> None:
    assert choose_short_titles({"X": ["Wft", "Wfm"]}) == {"X": "Wft"}


def test_an_abbreviation_claimed_by_several_regulations_never_wins() -> None:
    chosen = choose_short_titles(
        {
            "BWBR0002656": ["BW", "BW Boek 1", "BW1"],
            "BWBR0005288": ["bw", "BW Boek 5", "BW5"],
            "BWBR0000001": ["BW"],
        }
    )

    assert chosen == {
        "BWBR0002656": "BW1",
        "BWBR0005288": "BW5",
        "BWBR0000001": None,
    }


def test_case_variants_of_one_regulation_are_one_claim() -> None:
    assert choose_short_titles({"BWBR0001840": ["GW", "Gw"]}) == {"BWBR0001840": "GW"}


def test_a_code_of_books_never_wins_even_when_one_book_is_loaded() -> None:
    # Only Boek 7 loaded: "BW" is claimed once, but it names every book.
    assert choose_short_titles({"BWBR0005290": ["BW", "BW Boek 7", "BW7"]}) == {
        "BWBR0005290": "BW7"
    }
