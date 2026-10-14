"""The codes whose books are regulations of their own, from the WTI abbreviations.

The fixture holds the WTI abbreviations of the regulations of the small database, the ten
books of the Burgerlijk Wetboek among them."""

from __future__ import annotations

import json

import pytest

from lawgraph.core.code_families import CODE_FAMILIES, DATA, families_from_wti
from tests.paths import fixture_text

WTI = json.loads(fixture_text("bwb_wti_abbreviations.json"))


def test_the_data_file_is_what_the_wti_gives() -> None:
    assert families_from_wti(WTI) == json.loads(DATA.read_text())["families"]
    assert CODE_FAMILIES["BW"]["6"] == "BWBR0005289"
    assert CODE_FAMILIES["BW"]["7A"] == "BWBR0006000"
    assert list(CODE_FAMILIES["BW"]) == [
        "1", "2", "3", "4", "5", "6", "7", "7A", "8", "10"
    ]  # fmt: skip


def test_a_shared_abbreviation_without_books_is_no_code() -> None:
    # two regulations that list one abbreviation, but no book of it
    wti = {"A": ["WVW", "WVW 1994"], "B": ["WVW"], "C": ["X", "X Boek 1"]}
    assert families_from_wti(wti) == {}


def test_one_book_loaded_is_no_code_until_another_lists_it_too() -> None:
    assert families_from_wti({"BWBR0005289": ["BW", "BW Boek 6", "BW6"]}) == {}
    # the code keeps the spelling most regulations give it
    three = {
        "BWBR0005289": ["BW", "BW Boek 6", "BW6"],
        "BWBR0002656": ["bw", "BW boek 1"],
        "BWBR0005290": ["BW", "BW Boek 7"],
    }
    assert families_from_wti(three) == {
        "BW": {"1": "BWBR0002656", "6": "BWBR0005289", "7": "BWBR0005290"}
    }


def test_the_cited_number_of_a_book_and_its_own_number_undo_each_other() -> None:
    from lawgraph.core.code_families import book_of, cited_number, native_number

    for code, books in CODE_FAMILIES.items():
        for book, bwb_id in books.items():
            assert book_of(bwb_id) == book_of(bwb_id.lower()) == book, code
            cited = cited_number(bwb_id, "12")
            assert cited == f"{book}:12"
            assert native_number(bwb_id, cited) == "12"
            assert native_number(bwb_id, cited.lower()) == "12"
            assert cited_number(bwb_id, cited) == cited
    assert cited_number("BWBR0005289", "162") == "6:162"
    assert native_number("BWBR0005289", "3:40") == "3:40"  # another book: left alone
    # the Awb is no book of a code: 8:69 is its own number
    assert cited_number("BWBR0005537", "8:69") == "8:69"
    assert native_number("BWBR0005537", "8:69") == "8:69"
    assert cited_number(None, "162") == "162"
    assert book_of("BWBR0005537") is None


def test_a_code_family_is_one_in_any_case(monkeypatch: pytest.MonkeyPatch) -> None:
    from lawgraph.core import code_families
    from lawgraph.core.code_families import family_of, is_code_family

    assert is_code_family("BW") and is_code_family("bw") and is_code_family("Bw ")
    assert not is_code_family("Awb")
    assert family_of("bwbr0005289") == "BW"
    assert family_of("BWBR0005537") is None
    monkeypatch.setitem(code_families.CODE_FAMILIES, "WvK", {"1": "BWBR0001234"})
    assert is_code_family("WVK") and is_code_family("wvk") and is_code_family("WvK")
    assert family_of("BWBR0001234") == "WvK"


def test_a_code_goes_by_its_name_too() -> None:
    from lawgraph.core.code_families import family_named

    assert family_named("Burgerlijk Wetboek") == "BW"
    assert family_named("burgerlijk wetboek") == "BW"
    assert family_named("bw") == "BW"
    assert family_named("Wetboek van Strafrecht") is None
