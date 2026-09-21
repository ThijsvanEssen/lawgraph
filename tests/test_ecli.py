"""ECLI recognition and source derivation live in core.identifiers."""

from __future__ import annotations

import pytest

from lawgraph.core.identifiers import ecli_source, find_eclis, is_ecli


def test_text_scanner_finds_alphanumeric_case_numbers() -> None:
    text = "Zie ECLI:NL:HR:2005:AU1234 en ECLI:CE:ECHR:2019:0101JUD001234510."

    assert find_eclis(text) == [
        "ECLI:NL:HR:2005:AU1234",
        "ECLI:CE:ECHR:2019:0101JUD001234510",
    ]


def test_sentence_punctuation_is_not_part_of_the_ecli() -> None:
    assert find_eclis("(ECLI:NL:HR:2020:1234).") == ["ECLI:NL:HR:2020:1234"]
    assert find_eclis("ECLI:NL:HR:2020:1234, ECLI:NL:RBAMS:2020:99.") == [
        "ECLI:NL:HR:2020:1234",
        "ECLI:NL:RBAMS:2020:99",
    ]


def test_duplicates_are_removed_and_case_is_normalised() -> None:
    assert find_eclis("ecli:nl:hr:2020:1 en ECLI:NL:HR:2020:1") == ["ECLI:NL:HR:2020:1"]
    assert find_eclis(None) == [] and find_eclis("") == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("ECLI:NL:HR:2020:1234", True),
        (" ecli:nl:rbams:2020:ab.12 ", True),
        ("ECLI:NL:HR:20:1234", False),
        ("ECLI:NL:HR:2020", False),
        ("not an ecli", False),
    ],
)
def test_is_ecli(value: str, expected: bool) -> None:
    assert is_ecli(value) is expected


def test_source_from_prefix() -> None:
    assert ecli_source("ECLI:NL:HR:2020:1") == "rechtspraak"
    assert ecli_source("ECLI:CE:ECHR:2019:1") == "echr"
    assert ecli_source("ECLI:EU:C:2019:1") == "cjeu"
    assert ecli_source("ECLI:DE:BGH:2019:1") is None and ecli_source(None) is None
