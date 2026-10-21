"""The marker of a footnote in a BWB text (``<sup>1</sup>`` after a word) is no digit of
that text but a mark of its own (``footnote_marks``): where it stood and its number. A
``<sup>`` is a footnote marker when the article or annex holds the footnote it points to, a
paragraph that opens with a ``<sup>`` of the same number; else it is an exponent (``m³``).

On the annexes of the Cyberbeveiligingswet (BWBR0052872), art. 24 of the Successiewet 1956
(BWBR0002226, a ``1)`` in a table header) and art. 2 of the Regeling aanwijzing aanbieders
essentiële diensten EZK (BWBR0045077, ``m<sup>3</sup>``)."""

from __future__ import annotations

from lawgraph.api.schemas.annexes import AnnexDTO
from lawgraph.api.schemas.articles import footnote_marks_from_props
from lawgraph.core.bwb_xml import (
    AnnexXml,
    ArticleXml,
    annex_props,
    article_props,
    parse_toestand,
)
from tests.asserts import show_items
from tests.paths import fixture_text


def _cbw_annex() -> AnnexXml:
    return parse_toestand(fixture_text("bwb_cbw_annexes_toestand.xml")).annexes[0]


def _article(fixture: str, number: str) -> ArticleXml:
    (article,) = [
        a for a in parse_toestand(fixture_text(fixture)).articles if a.number == number
    ]
    return article


def test_a_footnote_marker_is_no_digit_of_the_word_before_it() -> None:
    annex = _cbw_annex()
    assert "2019/9441" not in annex.text
    first = annex.footnote_marks[0]
    assert first.number == "1"
    assert annex.text[: first.at].endswith("57, van Richtlijn (EU) 2019/944")
    assert annex.text[first.at :].startswith(", die de functie verrichten")


def test_every_marker_of_an_annex_is_a_mark_and_its_footnote_keeps_its_number() -> None:
    annex = _cbw_annex()
    (table,) = annex.tables
    # 22 footnotes, each marked in the table
    numbers = [mark.number for mark in annex.footnote_marks]
    assert numbers[:3] == ["1", "2", "3"]
    assert {mark.number for mark in annex.footnote_marks} == {
        str(n) for n in range(1, 23)
    }
    outside = [m for m in annex.footnote_marks if not table.start <= m.at <= table.end]
    assert not outside, show_items(outside)
    # the footnote itself: a paragraph after the table that opens with its number
    footnotes = annex.text[table.end :].lstrip("\n").split("\n")
    assert footnotes[0].startswith(
        "1 Richtlijn (EU) 2019/944 van het Europees Parlement"
    )


def test_a_marker_in_a_table_header_of_an_article_is_a_mark() -> None:
    article = _article("bwb_successiewet_footnote_toestand.xml", "24")
    assert "rechte lijn1)" not in article.text
    (mark,) = article.footnote_marks
    assert mark.number == "1"
    assert article.text[: mark.at].endswith(
        "indien verkregen door partner of afstammelingen in de rechte lijn"
    )
    assert "\n1 Voor afstammelingen in de tweede of verdere graad" in article.text
    shifted = [r for r in article.references if article.text[r.start : r.end] != r.text]
    assert not shifted, show_items(shifted)


def test_an_exponent_is_text() -> None:
    article = _article("bwb_aanbieders_ezk_toestand.xml", "2")
    assert "600.000 m3" in article.text
    assert article.footnote_marks == ()


def test_the_marks_are_props_and_fields_of_the_api() -> None:
    article = _article("bwb_successiewet_footnote_toestand.xml", "24")
    props = article_props(article, "BWBR0002226", "Successiewet 1956", 0)
    (mark,) = props["footnote_marks"]
    assert mark == {"at": article.footnote_marks[0].at, "number": "1"}
    assert [m.model_dump() for m in footnote_marks_from_props(props)] == [mark]
    # a mark past the text is left out
    assert footnote_marks_from_props({"text": "ab", "footnote_marks": [mark]}) == []
    assert "footnote_marks" not in article_props(
        _article("bwb_aanbieders_ezk_toestand.xml", "2"), "BWBR0045077", None, 0
    )

    annex = _cbw_annex()
    props = annex_props(annex, "BWBR0052872", None, 0)
    dto = AnnexDTO.from_document({"id": "annexes/a", "key": "a", "props": props})
    assert len(dto.footnote_marks) == len(annex.footnote_marks)
