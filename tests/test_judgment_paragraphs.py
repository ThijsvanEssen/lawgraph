"""The paragraphs of a judgment, with the number they print and the id that names them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lawgraph.core.judgments import extract_sections, parse_judgment
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
