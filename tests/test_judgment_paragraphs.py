"""The paragraphs of a judgment, with the number they print and the id that names them."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from lawgraph.core.judgments import (
    extract_judgment_text,
    extract_sections,
    parse_judgment,
)
from lawgraph.core.props import JudgmentProps

FIXTURES = Path(__file__).parent / "fixtures"


def _paragraphs(xml: str) -> list[dict[str, Any]]:
    return extract_sections(parse_judgment(f"<open>{xml}</open>"))


def _fixture(name: str) -> list[dict[str, Any]]:
    return extract_sections(parse_judgment((FIXTURES / name).read_text()))


def _brief(paragraphs: list[dict[str, Any]]) -> list[tuple[str, str | None, str, str]]:
    return [(p["id"], p["number"], p["kind"], p["text"][:12]) for p in paragraphs]


def test_a_numbered_unit_of_the_hoge_raad_is_a_paragraph_with_its_printed_number() -> (
    None
):
    """HR 2021:1215: sections with a numbered title, paragroups with an ``<nr>``."""
    paragraphs = _fixture("rechtspraak_hr_2021_1215.xml")

    assert _brief(paragraphs)[1:9] == [
        ("kop-1", "1", "heading", "De procedure"),
        ("rov-1.1", "1.1", "body", "Verzoeker he"),
        ("rov-1.2", "1.2", "body", "Bij op 18 ju"),
        ("kop-2", "2", "heading", "Beoordeling "),
        ("rov-2.1", "2.1", "body", "Ingevolge ar"),
        ("rov-2.2", "2.2", "body", "Verzoeker he"),
        ("rov-2.3", "2.3", "body", "Ingevolge ar"),
        ("rov-2.4", "2.4", "body", "De faxbrief "),
    ]
    # Without a number the position names it; the number is no part of the text.
    assert paragraphs[0]["id"] == "p-1" and paragraphs[0]["kind"] == "subheading"
    assert not paragraphs[2]["text"].startswith("1.1")


def test_a_number_that_the_text_opens_with_is_the_printed_number() -> None:
    """RvS 2019:1427 has no markup for it: "1.    Bij het besluit ..."."""
    paragraphs = _fixture("rechtspraak_rvs_2019_1427.xml")

    numbered = [p for p in paragraphs if p["number"]]
    assert [p["id"] for p in numbered[:3]] == ["rov-1", "rov-2", "rov-3"]
    assert numbered[0]["text"].startswith("Bij het besluit omtrent")
    # The paragraph after "2." that continues it has none: it is named by its position.
    follow = paragraphs[paragraphs.index(numbered[1]) + 1]
    assert follow["number"] is None and follow["id"].startswith("p-")


def test_the_ids_are_unique_and_a_repeated_number_gets_its_occurrence() -> None:
    paragraphs = _paragraphs(
        "<uitspraak>"
        "<section><title><nr>1</nr>Procesverloop</title>"
        "<para>1.  Eerste.</para><para>2.  Tweede.</para></section>"
        "<section><title><nr>2</nr>Overwegingen</title>"
        "<para>1.  Weer eerste.</para></section>"
        "</uitspraak>"
    )

    assert [p["id"] for p in paragraphs] == [
        "kop-1",
        "rov-1",
        "rov-2",
        "kop-2",
        "rov-1_2",
    ]


def test_the_own_text_of_a_unit_is_one_paragraph_and_a_nested_unit_another() -> None:
    paragraphs = _paragraphs(
        "<uitspraak><section><title><nr>3</nr>Beoordeling</title>"
        "<paragroup><nr>3.1</nr><para>Eerst.</para><para>Dan.</para>"
        "<paragroup><nr>3.1.1</nr><parablock><para>Diep.</para></parablock></paragroup>"
        "<paragroup><nr>3.1.2</nr><para>Dieper.</para></paragroup></paragroup>"
        "</section></uitspraak>"
    )

    assert [(p["id"], p["text"]) for p in paragraphs[1:]] == [
        ("rov-3.1", "Eerst.\n\nDan."),
        ("rov-3.1.1", "Diep."),
        ("rov-3.1.2", "Dieper."),
    ]


def test_a_date_or_an_amount_at_the_start_of_a_sentence_is_no_number() -> None:
    paragraphs = _paragraphs(
        "<uitspraak><para>1 februari 2013 kwam hij thuis.</para>"
        "<para>1.500 euro is te veel.</para><para>12. Twaalf.</para></uitspraak>"
    )

    assert [(p["number"], p["text"]) for p in paragraphs] == [
        (None, "1 februari 2013 kwam hij thuis."),
        (None, "1.500 euro is te veel."),
        ("12", "Twaalf."),
    ]


def test_inline_markup_stays_inside_the_word_and_footnotes_are_left_out() -> None:
    (paragraph,) = _paragraphs(
        "<uitspraak><para>Het <emphasis>arrest</emphasis>je van art. 6:162 BW"
        '<footnote-ref linkend="x"/> hier.</para><footnote><para>noot</para></footnote>'
        "</uitspraak>"
    )

    assert paragraph["text"] == "Het arrestje van art. 6:162 BW hier."


def test_a_judgment_without_a_uitspraak_has_no_paragraphs() -> None:
    assert _paragraphs("<inhoudsindicatie>Samenvatting</inhoudsindicatie>") == []


def test_the_paragraphs_are_valid_judgment_props() -> None:
    paragraphs = _fixture("rechtspraak_hr_2021_1215.xml")

    JudgmentProps.model_validate({"paragraphs": paragraphs})


# The kop: court, case number and parties, written in an <uitspraak.info>, in bridgeheads,
# in loose paragraphs or in sections whose titles are party names.
KOP_FIXTURES = [
    "rechtspraak_gharl_2026_6060.xml",  # everything in <uitspraak.info>, a bridgehead party
    "rechtspraak_ghdha_2026_2908.xml",  # emphasis in a <para> of a <parablock>
    "rechtspraak_rvs_2026_5668.xml",  # no <uitspraak.info>: one <parablock> holds it all
    "rechtspraak_gharl_2026_6033.xml",  # party names as the titles of sections
    "rechtspraak_hr_2019_1278.xml",  # <?linebreak?> inside the party lines
    "rechtspraak_rbams_2024_81.xml",  # two joined cases, a party per bridgehead
    "rechtspraak_ghams_2026_2707.xml",  # a table of designations
]


def _letters(text: str) -> str:
    """Text as compared: letters and digits only (a number is split off its paragraph)."""
    return re.sub(r"\W", "", text)


@pytest.mark.parametrize("name", KOP_FIXTURES)
def test_every_line_of_the_text_is_in_a_paragraph(name: str) -> None:
    root = parse_judgment((FIXTURES / name).read_text())
    _, text = extract_judgment_text(root)
    paragraphs = extract_sections(root)
    printed = _letters(" ".join(f"{p['number'] or ''} {p['text']}" for p in paragraphs))

    lines = [line for line in (text or "").splitlines() if _letters(line)]
    assert lines
    assert [line for line in lines if _letters(line) not in printed] == []


@pytest.mark.parametrize("name", KOP_FIXTURES)
def test_the_kop_is_the_first_paragraph_and_holds_every_line_before_the_heading(
    name: str,
) -> None:
    """The paragraph after it opens with the heading; a court that writes its headings as
    plain paragraphs (the Raad van State) has a ``body`` there."""
    root = parse_judgment((FIXTURES / name).read_text())
    kop, heading = extract_sections(root)[:2]
    _, text = extract_judgment_text(root)
    before = (text or "").split(heading["text"].splitlines()[0])[0]

    assert kop["kind"] == "subheading"
    for line in before.splitlines():
        assert _letters(line) in _letters(kop["text"])


def test_the_kop_keeps_the_party_it_lost_before() -> None:
    """GHARL 2026:6060: "in de strafzaak tegen" and "[verdachte] ," were left out, the
    first a <para> with emphasis beside others in its <parablock>, the second a bridgehead."""
    root = parse_judgment((FIXTURES / "rechtspraak_gharl_2026_6060.xml").read_text())
    kop, heading = extract_sections(root)[:2]

    assert kop["text"].split("\n\n")[4:7] == [
        "Arrest van de meervoudige kamer voor strafzaken van het gerechtshof "
        "Arnhem-Leeuwarden, zittingsplaats Arnhem, gewezen op het hoger beroep, ingesteld "
        "tegen het vonnis van de rechtbank Gelderland, zittingsplaats Zutphen, van 13 "
        "oktober 2025 met parketnummer 05-028450-25 in de strafzaak tegen",
        "[verdachte] ,",
        "geboren op [geboortedatum] 1987 in [geboorteplaats] ,",
    ]
    assert (heading["kind"], heading["text"]) == ("heading", "Hoger beroep")


def test_a_line_break_parts_the_lines_of_the_kop_and_is_a_newline_in_the_text() -> None:
    root = parse_judgment((FIXTURES / "rechtspraak_hr_2019_1278.xml").read_text())

    assert (
        "[eiseres 1] ,\n\nwonende te [woonplaats] ,"
        in extract_sections(root)[0]["text"]
    )
    assert "[eiseres 1] ,\n" in (extract_judgment_text(root)[1] or "")


def test_text_before_a_late_first_heading_is_no_kop() -> None:
    """Old judgments tell their story before a first heading, if they have one."""
    prose = "Het hof heeft overwogen dat " + "de zaak zo gaat " * 20
    paragraphs = _paragraphs(
        "<uitspraak>"
        + f"<para>{prose}</para>" * 5
        + "<para>Beoordeling</para></uitspraak>"
    )

    assert [p["kind"] for p in paragraphs] == ["body"] * 6
