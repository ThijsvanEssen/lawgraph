"""Tests for the single CELEX pattern, type-letter table and parser."""

from __future__ import annotations

import pytest

from lawgraph.core.citations import format_celex
from lawgraph.core.identifiers import (
    CELEX_KIND_TO_LETTER,
    CELEX_PATTERN,
    find_celex_ids,
    parse_celex,
)
from lawgraph.pipelines.normalize.eurlex import _derive_eu_citation_title
from lawgraph.pipelines.semantic.instrument_relations import detect_celex_references


def test_sector3_letters_follow_eu_convention() -> None:
    assert CELEX_KIND_TO_LETTER == {
        "regulation": "R",
        "directive": "L",
        "decision": "D",
        "framework_decision": "F",
        "recommendation": "H",
    }


def test_format_celex_uses_the_table() -> None:
    assert format_celex("decision", "2011", "24") == "32011D0024"
    assert format_celex("framework_decision", "2002", "584") == "32002F0584"


@pytest.mark.parametrize("letter", list("CLRDF"))
def test_celex_pattern_matches_lenient_letters(letter: str) -> None:
    assert CELEX_PATTERN.search(f"zie 32010{letter}0064.")


def test_celex_pattern_is_case_insensitive_and_bounded() -> None:
    assert find_celex_ids("a 32010l0064 en 32016R0679, niet 132010L0064") == [
        "32010L0064",
        "32016R0679",
    ]


def test_celex_pattern_requires_four_digit_number() -> None:
    assert find_celex_ids("32010L064 en 32010L00640") == []


def test_instrument_relations_delegates_to_shared_pattern() -> None:
    assert detect_celex_references("32019L1158 en 32009l0028") == [
        "32019L1158",
        "32009L0028",
    ]


def test_parse_celex_directive() -> None:
    parsed = parse_celex("32010l0064")
    assert parsed is not None
    assert (parsed.year, parsed.letter, parsed.number, parsed.kind) == (
        "2010",
        "L",
        "0064",
        "directive",
    )


@pytest.mark.parametrize(
    ("celex", "kind"),
    [
        ("32016R0679", "regulation"),
        ("32011D0024", "decision"),
        ("32002F0584", "framework_decision"),
    ],
)
def test_parse_celex_kinds(celex: str, kind: str) -> None:
    parsed = parse_celex(celex)
    assert parsed is not None and parsed.kind == kind


def test_parse_celex_lenient_c_has_no_kind() -> None:
    parsed = parse_celex("32011C0024")
    assert parsed is not None and parsed.kind is None


@pytest.mark.parametrize("value", ["", "12010L0064", "32010L", "32010X0064", "abc"])
def test_parse_celex_rejects_non_celex(value: str) -> None:
    assert parse_celex(value) is None


def test_parse_celex_accepts_any_number_length() -> None:
    parsed = parse_celex("32010L64")
    assert parsed is not None and parsed.number == "64"


@pytest.mark.parametrize(
    ("celex", "title"),
    [
        ("32010L0064", "Richtlijn 2010/64/EU"),
        ("32016R0679", "Verordening 2016/679/EU"),
        ("32011D0024", "Besluit 2011/24/EU"),
        ("32002F0584", "Kaderbesluit 2002/584/JBZ"),
        ("32011C0024", None),
        ("nonsense", None),
    ],
)
def test_derive_eu_citation_title(celex: str, title: str | None) -> None:
    assert _derive_eu_citation_title(celex) == title


def test_the_query_regex_finds_every_text_the_pattern_finds() -> None:
    """The server-side prefilter of fill-gaps may send too much, never too little."""
    import re

    from lawgraph.core.identifiers import CELEX_AQL_REGEX, find_celex_ids

    prefilter = re.compile(
        CELEX_AQL_REGEX
    )  # the syntax AQL's REGEX_TEST shares with re
    texts = [
        "zie richtlijn 32016L0680 en verordening 32016r0679.",
        "geen verwijzing, wel een getal 320160680 en een jaar 2016",
        "x32016L0680x",  # no word boundary: the prefilter sends it, the pattern refuses it
        "",
    ]
    for text in texts:
        assert bool(prefilter.search(text)) >= bool(find_celex_ids(text)), text
    assert [bool(prefilter.search(t)) for t in texts] == [True, False, True, False]


def test_fill_gaps_lets_the_server_leave_out_the_texts_without_a_celex_id() -> None:
    from lawgraph.commands import fill_gaps
    from lawgraph.core.identifiers import CELEX_AQL_REGEX

    asked: list[tuple[str, dict]] = []

    class Store:
        def query(self, aql, bind_vars=None, **_kw):
            asked.append((aql, dict(bind_vars or {})))
            if "REGEX_TEST" in aql:
                return iter(["krachtens richtlijn 32010L0064 en 32016L0680"])
            return iter(["32016L0680"] if "instruments" in aql else [])

    assert fill_gaps._query_stub_celex_ids(Store()) == ["32010L0064"]  # type: ignore[arg-type]
    scan = [bind for aql, bind in asked if "REGEX_TEST(art.props.text, @celex)" in aql]
    assert scan == [{"celex": CELEX_AQL_REGEX}]
