"""A footnote the BWB writes where its marker stands (``<noot>`` with ``<noot.nr>`` and
``<noot.al>``) is no text of the article: its marker is a mark (``footnote_marks``) that
names the footnote, and the footnote is one of ``footnotes``, ``{number, text}``, its
links references of that footnote.

On Bijlage I of the Meststoffenwet (BWBR0004054, two footnotes ``1)`` in one annex) and
art. 15, 44 and 45 of the partnership agreement with Uzbekistan (BWBV0007162: a footnote
with a link to an EU regulation, one in the heading of the article)."""

from __future__ import annotations

from lawgraph.api.schemas.annexes import AnnexDTO
from lawgraph.api.schemas.articles import (
    ArticleSummaryDTO,
    footnote_marks_from_props,
    references_from_props,
)
from lawgraph.core.bwb_xml import (
    AnnexXml,
    ArticleXml,
    annex_props,
    article_props,
    article_version_props,
    parse_toestand,
)
from lawgraph.pipelines.semantic._bwb_references import hits_from_references
from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline
from tests.asserts import show_items
from tests.paths import fixture_text

_TREATY = "bwb_verdrag_oezbekistan_noot_toestand.xml"


def _annex() -> AnnexXml:
    (annex,) = parse_toestand(
        fixture_text("bwb_meststoffenwet_noot_toestand.xml")
    ).annexes
    return annex


def _article(number: str) -> ArticleXml:
    """The first article *number* of the treaty (its protocol numbers its own)."""
    return next(
        a for a in parse_toestand(fixture_text(_TREATY)).articles if a.number == number
    )


def test_a_noot_is_no_text_but_a_mark_and_a_footnote() -> None:
    annex = _annex()
    assert "Dalfsen 1)" not in annex.text
    assert "Tot het grondgebied van de gemeente Dalfsen" not in annex.text
    (mark,) = [
        m for m in annex.footnote_marks if annex.text[: m.at].endswith("Dalfsen")
    ]
    assert mark.number == "1"
    assert mark.footnote is not None
    footnote = annex.footnotes[mark.footnote]
    assert footnote.number == "1"
    assert footnote.text.startswith("Tot het grondgebied van de gemeente Dalfsen")


def test_each_mark_names_its_own_footnote_where_numbers_repeat() -> None:
    annex = _annex()
    assert len(annex.footnotes) == len(annex.footnote_marks) == 5
    assert [m.footnote for m in annex.footnote_marks] == [0, 1, 2, 3, 4]
    numbers = [footnote.number for footnote in annex.footnotes]
    assert numbers.count("1") == 2, numbers
    (breda,) = [m for m in annex.footnote_marks if annex.text[: m.at].endswith("Breda")]
    assert annex.footnotes[breda.footnote or 0].text.startswith(
        "Tot het grondgebied van de gemeente Breda"
    )


def test_the_description_of_an_annex_leaves_a_noot_out() -> None:
    lines = (_annex().description or "").split("\n")
    assert "Dalfsen" in lines, show_items(lines[:20])
    assert not [line for line in lines if line.startswith(("Dalfsen ", "Breda "))]


def test_a_link_in_a_footnote_is_a_reference_of_that_footnote() -> None:
    article = _article("15")
    assert "Raad1)" not in article.text and "(PB EU L 311" not in article.text
    (footnote,) = article.footnotes
    assert footnote.number == "1"
    (reference,) = [r for r in footnote.references if r.celex]
    assert reference.celex == "32016R1953"
    assert footnote.text[reference.start : reference.end] == reference.text
    shifted = [r for r in article.references if article.text[r.start : r.end] != r.text]
    assert not shifted, show_items(shifted)


def test_a_noot_in_the_heading_is_a_footnote_without_a_mark() -> None:
    article = _article("44")
    assert article.heading == "Uitvoervergunningsprocedures"
    (footnote,) = article.footnotes
    assert footnote.number == "4"
    assert footnote.text.startswith("Ter verduidelijking: geen van de bepalingen")
    assert article.footnote_marks == ()


def test_the_footnotes_are_props_and_fields_of_the_api() -> None:
    article = _article("15")
    props = article_props(article, "BWBV0007162", None, 0)
    (footnote,) = props["footnotes"]
    assert footnote == {"number": "1", "text": article.footnotes[0].text}
    (mark,) = props["footnote_marks"]
    assert mark["footnote"] == 0
    assert article_version_props(article, "BWBV0007162", None, 0)["footnotes"] == [
        footnote
    ]
    # a reference of a footnote names it; the text's references leave it out
    (in_note,) = [r for r in props["references"] if r.get("footnote") is not None]
    assert in_note["footnote"] == 0 and in_note["celex"] == "32016R1953"
    in_text = references_from_props(props, set())
    wrong = [r for r in in_text if r.footnote is not None]
    assert not wrong, show_items(wrong)
    (listed,) = references_from_props(props, set(), footnotes=True)
    assert listed.footnote == 0 and listed.celex == "32016R1953"

    dto = ArticleSummaryDTO.from_document(
        {"id": "articles/a", "key": "a", "props": props}
    )
    assert [f.model_dump() for f in dto.footnotes] == [footnote]
    assert [m.footnote for m in footnote_marks_from_props(props)] == [0]
    # a mark that names no footnote of the article names none
    stray = {**props, "footnotes": None}
    assert [m.footnote for m in footnote_marks_from_props(stray)] == [None]

    annex = _annex()
    annex_dto = AnnexDTO.from_document(
        {"id": "annexes/a", "key": "a", "props": annex_props(annex, "BWBR0004054")}
    )
    assert len(annex_dto.footnotes) == 5


def test_a_reference_in_a_footnote_cites_without_a_span_of_the_text() -> None:
    references = [
        {
            "kind": "extref",
            "bwb_id": "BWBR0005537",
            "article": "1:1",
            "doc": "jci1.3:c:BWBR0005537&artikel=1:1",
            "text": "artikel 1:1 Awb",
            "start": 4,
            "end": 19,
            "footnote": 0,
        }
    ]
    (hit,) = hits_from_references(references, "BWBV0007162", "15")
    assert hit.footnote == 0
    meta = BWBSemanticPipeline._edge_meta(hit)
    assert meta["footnote"] == 0
    assert "start" not in meta and "end" not in meta, meta
