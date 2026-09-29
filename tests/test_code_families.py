"""The codes whose books are regulations of their own, from the WTI abbreviations.

The fixture holds the WTI abbreviations of the regulations of the small database, the ten
books of the Burgerlijk Wetboek among them."""

from __future__ import annotations

import json
from pathlib import Path

from lawgraph.core.code_families import CODE_FAMILIES, DATA, families_from_wti

WTI = json.loads(
    (Path(__file__).parent / "fixtures" / "bwb_wti_abbreviations.json").read_text()
)


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
