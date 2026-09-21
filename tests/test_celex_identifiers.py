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


# The links of BWBR0001854, BWBR0001860 and others, as KOOP publishes them: one Celex link
# in eight (5,974 of 48,767 in the rebuild of 2026-09-21) has the year where the number
# belongs and digits that are no year where the year belongs. Cellar has none of those ids
# and has every rebuilt one below.
@pytest.mark.parametrize(
    ("doc", "text", "celex"),
    [
        ("32684R2021", "verordening (EU) 2021/784", "32021R0784"),
        ("31923R2021", "Verordening (EU) 2021/23", "32021R0023"),
        ("32365R2015", "(EU) 2015/2365", "32015R2365"),
        # number/year is how only a regulation is cited, whatever letter the link has
        ("32993L2010", "nr. 1093/2010", "32010R1093"),
        ("32496L2014", "596/2014", "32014R0596"),
        # nothing in the text to rebuild it from: no id beats a guessed one
        ("32112R0260", "Verordening (EU) nr. 260/212", None),
        ("32508R0089", "89/608/EEG", None),
    ],
)
def test_a_celex_link_with_an_impossible_year_is_rebuilt_from_its_text(
    doc: str, text: str, celex: str | None
) -> None:
    from lawgraph.core.identifiers import rebuilt_celex

    assert rebuilt_celex(doc, text) == celex


def test_the_eu_acts_of_a_regulation_are_the_possible_ids_and_the_rebuilt_ones() -> (
    None
):
    from lawgraph.core.bwb_xml import celex_refs

    xml = (
        '<al>zie <extref doc="32016R0679" label="verordening" reeks="Celex">de AVG</extref>,'
        ' <extref doc="32684R2021" label="verordening" reeks="Celex">verordening (EU)'
        "\n 2021/<nadruk>784</nadruk></extref> en"
        ' <extref doc="32112R0260" reeks="Celex">Verordening (EU) nr. 260/212</extref>'
        " <!-- 32010L0064 --></al>"
    )
    assert celex_refs(xml) == ["32010L0064", "32016R0679", "32021R0784"]
