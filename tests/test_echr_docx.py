"""The text and paragraphs of an ECHR judgment, from the body of its HUDOC DOCX."""

from __future__ import annotations

import pathlib

import pytest

from lawgraph.core.echr_docx import read_judgment
from lawgraph.core.judgments import text_id

# Beumer v. the Netherlands (001-61254), the word/document.xml of the DOCX HUDOC serves.
BEUMER = (
    pathlib.Path(__file__).parent / "fixtures" / "hudoc_001_61254_document.xml"
).read_text()

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _document(*paragraphs: str) -> str:
    return (
        f'<w:document xmlns:w="{W}" xmlns:mc="{MC}"><w:body>'
        + "".join(paragraphs)
        + "</w:body></w:document>"
    )


def _p(style: str, text: str, extra: str = "") -> str:
    return (
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
        f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>{extra}</w:p>'
    )


def test_a_judgment_reads_as_its_paragraphs_in_order() -> None:
    text, paragraphs = read_judgment(BEUMER)
    by_id = {p["id"]: p for p in paragraphs}
    assert paragraphs[0] == {
        "id": text_id("SECOND SECTION"),
        "number": None,
        "kind": "body",
        "text": "SECOND SECTION",
    }
    assert by_id[text_id("PROCEDURE")]["kind"] == "heading"
    assert by_id["par-1"]["number"] == "1"
    assert by_id["par-1"]["text"].startswith("The case originated in an application")
    assert by_id["par-64"]["kind"] == "body"
    # "I. THE CIRCUMSTANCES OF THE CASE" and, under THE LAW, a second "I."
    assert by_id["kop-i"] == {
        "id": "kop-i",
        "number": "I",
        "kind": "subheading",
        "text": "THE CIRCUMSTANCES OF THE CASE",
    }
    assert by_id["kop-ii_2"]["text"] == "APPLICATION OF ARTICLE 41 OF THE CONVENTION"
    assert len({p["id"] for p in paragraphs}) == len(paragraphs)
    # the text as printed: numbers included, a blank line between paragraphs
    assert text is not None and "\n\n1. The case originated" in text


def test_the_styles_of_the_grand_chamber_template_and_a_table_of_contents() -> None:
    _, paragraphs = read_judgment(
        _document(
            _p("TOC1", "THE FACTS 1"),
            _p("ECHRHeading1", "THE FACTS"),
            _p("ECHRHeading2", "A. The background"),
            _p("ECHRPara", "1.  The applicant was born in 1970."),
            _p("ECHRParaQuote", "2.  A quoted number is no paragraph."),
            _p("JuList", "1. Holds that there has been a violation;"),
            _p("JuHeader", "RUNNING HEADER"),
        )
    )
    assert [(p["id"], p["kind"], p["number"]) for p in paragraphs] == [
        (text_id("THE FACTS"), "heading", None),
        ("kop-a", "subheading", "A"),
        ("par-1", "body", "1"),
        (text_id("2.  A quoted number is no paragraph."), "body", None),
        (text_id("1. Holds that there has been a violation;"), "body", None),
        (text_id("RUNNING HEADER"), "body", None),
    ]


def test_a_separate_opinion_numbering_from_1_again_keeps_its_ids_unique() -> None:
    _, paragraphs = read_judgment(
        _document(_p("JuPara", "1.  The Court."), _p("OpiPara", "1.  I agree."))
    )
    assert [p["id"] for p in paragraphs] == ["par-1", "par-1_2"]


def test_the_fallback_copy_of_a_text_box_is_read_once() -> None:
    box = (
        "<w:r><mc:AlternateContent><mc:Choice><w:txbxContent>"
        + _p("JuPara", "In the box.")
        + "</w:txbxContent></mc:Choice><mc:Fallback><w:txbxContent>"
        + _p("JuPara", "In the box.")
        + "</w:txbxContent></mc:Fallback></mc:AlternateContent></w:r>"
    )
    text, paragraphs = read_judgment(_document(_p("JuPara", "Outside.", box)))
    assert [p["text"] for p in paragraphs] == ["Outside.", "In the box."]
    assert text == "Outside.\n\nIn the box."


def test_what_is_not_xml_is_an_error() -> None:
    with pytest.raises(ValueError):
        read_judgment("<w:document")
