"""The shape of an ECLI, its source and its key, from core.ecli."""

from __future__ import annotations

import pytest

from lawgraph.core.ecli import cited_eclis, ecli_of_key, ecli_source, is_ecli


def test_text_scanner_finds_alphanumeric_case_numbers() -> None:
    text = "Zie ECLI:NL:HR:2005:AU1234 en ECLI:CE:ECHR:2019:0101JUD001234510."

    assert cited_eclis(text) == [
        "ECLI:NL:HR:2005:AU1234",
        "ECLI:CE:ECHR:2019:0101JUD001234510",
    ]


def test_sentence_punctuation_is_not_part_of_the_ecli() -> None:
    assert cited_eclis("(ECLI:NL:HR:2020:1234).") == ["ECLI:NL:HR:2020:1234"]
    assert cited_eclis("ECLI:NL:HR:2020:1234, ECLI:NL:RBAMS:2020:99.") == [
        "ECLI:NL:HR:2020:1234",
        "ECLI:NL:RBAMS:2020:99",
    ]


def test_duplicates_are_removed_and_case_is_normalised() -> None:
    assert cited_eclis("ecli:nl:hr:2020:1 en ECLI:NL:HR:2020:1") == [
        "ECLI:NL:HR:2020:1"
    ]
    assert cited_eclis(None) == [] and cited_eclis("") == []


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


def test_the_ecli_of_a_judgment_key() -> None:
    assert ecli_of_key("ecli_nl_hr_2019_2006") == "ECLI:NL:HR:2019:2006"
    assert ecli_of_key("ecli_be_cass_2019_arr_20190101_1") is None
    assert ecli_of_key("bwbr0005289") is None
