"""The structure of a BWB article: aanhef, leden and onderdelen as spans of its text."""

from __future__ import annotations

import json
import pathlib

import pytest

from lawgraph.core.bwb_xml import (
    ArticleXml,
    article_props,
    article_version_props,
    parse_toestand,
)
from lawgraph.core.models import Node, NodeType

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def grondwet():
    return parse_toestand((FIXTURES / "bwb_grondwet_toestand.xml").read_text())


def _article(xml: str) -> ArticleXml:
    """The one article of an inline ``<artikel>``."""
    (article,) = parse_toestand(
        f"<toestand bwb-id='BWBR0000001'>{xml}</toestand>"
    ).articles
    return article


def _shape(article: ArticleXml) -> list[tuple[str, str, str | None, str]]:
    return [
        (p.id, p.kind, p.number, article.text[p.start : p.end]) for p in article.parts
    ]


# ── the text does not change when the structure is read ──────────────────────


def test_the_text_and_references_of_the_fixtures_are_what_they_always_were() -> None:
    """Recorded before the structure of an article was read: text and offsets stay valid."""
    golden = json.loads((FIXTURES / "bwb_article_text_golden.json").read_text())

    for name, expected in golden.items():
        articles = parse_toestand((FIXTURES / name).read_text()).articles
        assert [a.text for a in articles] == [e["text"] for e in expected], name
        assert [
            [
                [r.kind, r.bwb_id, r.article, r.doc, r.text, r.start, r.end]
                for r in a.references
            ]
            for a in articles
        ] == [e["refs"] for e in expected], name


# ── the parts ────────────────────────────────────────────────────────────────

_LEDEN_AND_LISTS = """
<artikel><kop><nr>5</nr></kop>
<lid><lidnr>1</lidnr><al>In dit artikel wordt verstaan onder:</al>
  <lijst><li><li.nr>a.</li.nr><al>een <extref doc="jci1.3:c:BWBR0001854&amp;artikel=287"
      bwb-id="BWBR0001854">artikel 287, eerste lid, onder a</extref>;</al></li>
  <li><li.nr>b.</li.nr><al>de volgende:</al>
    <lijst><li><li.nr>1°.</li.nr><al>een</al></li><li><li.nr>2°.</li.nr><al>twee</al></li></lijst></li>
  <li><li.nr>c.</li.nr><al>slot.</al></li></lijst></lid>
<lid><lidnr>2</lidnr><al>Tweede lid, zie <intref doc="jci1.3:c:BWBR0001840&amp;artikel=91"
    bwb-id="BWBR0001840">artikel 91, derde lid</intref>.</al></lid>
<lid><lidnr>2a</lidnr><al>Nog een.</al></lid>
</artikel>"""


def test_leden_onderdelen_and_nested_onderdelen_are_spans_of_the_text() -> None:
    article = _article(_LEDEN_AND_LISTS)

    assert article.text == (
        "1. In dit artikel wordt verstaan onder:\n"
        "a. een artikel 287, eerste lid, onder a;\n"
        "b. de volgende:\n1°. een\n2°. twee\nc. slot.\n"
        "2. Tweede lid, zie artikel 91, derde lid.\n2a. Nog een."
    )
    assert _shape(article) == [
        (
            "lid-1",
            "lid",
            "1",
            "In dit artikel wordt verstaan onder:\n"
            "a. een artikel 287, eerste lid, onder a;\n"
            "b. de volgende:\n1°. een\n2°. twee\nc. slot.",
        ),
        ("lid-1-aanhef", "aanhef", None, "In dit artikel wordt verstaan onder:"),
        ("lid-1-onder-a", "onderdeel", "a", "een artikel 287, eerste lid, onder a;"),
        ("lid-1-onder-b", "onderdeel", "b", "de volgende:\n1°. een\n2°. twee"),
        ("lid-1-onder-b-onder-1", "onderdeel", "1°", "een"),
        ("lid-1-onder-b-onder-2", "onderdeel", "2°", "twee"),
        ("lid-1-onder-c", "onderdeel", "c", "slot."),
        ("lid-2", "lid", "2", "Tweede lid, zie artikel 91, derde lid."),
        ("lid-2a", "lid", "2a", "Nog een."),
    ]


def test_references_name_the_lid_and_onderdeel_their_text_says() -> None:
    article = _article(_LEDEN_AND_LISTS)

    first, second = article.references
    assert (first.qualifier.leden, first.qualifier.onderdelen) == (("1",), ("a",))
    assert (second.qualifier.leden, second.qualifier.onderdelen) == (("3",), ())
    assert all(article.text[r.start : r.end] == r.text for r in article.references)


def test_a_paragraph_next_to_the_leden_is_no_part() -> None:
    article = _article(
        """<artikel><kop><nr>5</nr></kop>
        <al>Dit artikel is nog niet in werking getreden.</al>
        <lid><lidnr>1</lidnr><al>Een.</al></lid>
        <lid><lidnr>2</lidnr><al>Twee.</al></lid></artikel>"""
    )

    assert (
        article.text
        == "Dit artikel is nog niet in werking getreden.\n1. Een.\n2. Twee."
    )
    assert _shape(article) == [
        ("lid-1", "lid", "1", "Een."),
        ("lid-2", "lid", "2", "Twee."),
    ]


def test_empty_leden_are_no_parts() -> None:
    article = _article(
        """<artikel><kop><nr>5</nr></kop>
        <lid><lidnr>1</lidnr></lid>
        <lid><lidnr>2</lidnr><al></al></lid>
        <lid><lidnr>3</lidnr><al>Drie.</al></lid>
        <lid><lidnr>4</lidnr><lijst><li><li.nr>a.</li.nr></li></lijst></lid></artikel>"""
    )

    assert article.text == "2. \n3. Drie.\n4."
    assert _shape(article) == [("lid-3", "lid", "3", "Drie.")]


def test_a_repealed_article_and_a_single_paragraph_have_no_parts() -> None:
    repealed = _article(
        '<artikel effect="vervallen"><kop><nr>5</nr></kop><al>Vervallen</al></artikel>'
    )
    single = _article("<artikel><kop><nr>5</nr></kop><al>Een tekst.</al></artikel>")

    assert repealed.parts == () and single.parts == ()


def test_an_article_without_leden_has_an_aanhef_and_onderdelen() -> None:
    article = _article(
        """<artikel><kop><nr>5</nr></kop>
        <al>In deze wet wordt verstaan onder:</al>
        <lijst><li><li.nr>a.</li.nr><al>alfa;</al></li>
        <li><li.nr>a.</li.nr><al>alfa nogmaals;</al></li>
        <li><li.nr>–</li.nr><al>streepje;</al></li><li><al>zonder teken.</al></li></lijst>
        <al>Slot na de lijst.</al></artikel>"""
    )

    assert _shape(article) == [
        ("aanhef", "aanhef", None, "In deze wet wordt verstaan onder:"),
        ("onder-a", "onderdeel", "a", "alfa;"),
        ("onder-a_2", "onderdeel", "a", "alfa nogmaals;"),
        ("onder-_3", "onderdeel", "–", "streepje;"),
        ("onder-_4", "onderdeel", None, "zonder teken."),
    ]


def test_a_lid_without_a_number_or_paragraph_is_still_a_part() -> None:
    article = _article(
        """<artikel><kop><nr>5</nr></kop>
        <lid><al>Zonder nummer.</al></lid>
        <lid><lidnr>2</lidnr><lijst><li><li.nr>a.</li.nr><al>alfa</al></li></lijst></lid>
        <lid><lidnr>3</lidnr><al>Aanhef:</al>
        <lijst><li><li.nr>a.</li.nr><al>alfa</al></li></lijst>
        <al>Afsluiting.</al></lid></artikel>"""
    )

    assert [p.id for p in article.parts] == [
        "lid-_1",
        "lid-2",
        "lid-2-onder-a",
        "lid-3",
        "lid-3-aanhef",
        "lid-3-onder-a",
    ]


def test_a_reference_after_an_empty_paragraph_keeps_a_valid_offset() -> None:
    article = _article(
        """<artikel><kop><nr>5</nr></kop><al></al>
        <al>Zie <extref doc="jci1.3:c:BWBR0001854&amp;artikel=2" bwb-id="BWBR0001854">artikel 2,
        onder a</extref>.</al></artikel>"""
    )

    (ref,) = article.references
    assert article.text[ref.start : ref.end] == ref.text
    assert ref.qualifier.onderdelen == ("a",)


def test_a_link_to_a_chapter_names_no_lid() -> None:
    article = _article(
        """<artikel><kop><nr>5</nr></kop><al>Zie
        <intref doc="jci1.3:c:BWBR0001840&amp;hoofdstuk=8" bwb-id="BWBR0001840">hoofdstuk 8,
        onder a</intref>.</al></artikel>"""
    )

    (ref,) = article.references
    assert ref.article is None and ref.qualifier.empty


def test_the_parts_of_every_fixture_article_fit_its_text(grondwet) -> None:
    assert any(article.parts for article in grondwet.articles)
    for article in grondwet.articles:
        ids = [p.id for p in article.parts]
        assert len(ids) == len(set(ids))
        assert [p.start for p in article.parts] == sorted(
            p.start for p in article.parts
        )
        for part in article.parts:
            assert 0 <= part.start < part.end <= len(article.text)
            assert article.text[part.start : part.end].strip()


def test_grondwet_article_7_has_four_leden(grondwet) -> None:
    art7 = next(a for a in grondwet.articles if a.path == "/Hoofdstuk1/Artikel7")

    assert [(p.id, p.number) for p in art7.parts] == [
        ("lid-1", "1"),
        ("lid-2", "2"),
        ("lid-3", "3"),
        ("lid-4", "4"),
    ]
    first = art7.parts[0]
    assert art7.text[first.start : first.end].startswith(
        "Niemand heeft voorafgaand verlof nodig"
    )


def test_the_jci_of_a_link_names_no_lid_so_the_text_is_read(grondwet) -> None:
    """Checked against real BWB XML: a ``doc`` stops at ``artikel``; the lid is in the text."""
    art92 = next(
        a for a in grondwet.articles if a.path == "/Hoofdstuk5/Paragraaf2/Artikel92"
    )

    (ref,) = art92.references
    assert "lid" not in ref.doc
    assert ref.qualifier.leden == ("3",)


# ── the props ────────────────────────────────────────────────────────────────


def test_props_carry_the_parts_as_offsets_and_the_references_with_their_qualifier() -> (
    None
):
    article = _article(_LEDEN_AND_LISTS)

    props = article_props(article, "BWBR0000001", "Wet", 0)
    version = article_version_props(article, "BWBR0000001", "Wet", 0)

    assert props["parts"][0] == {
        "id": "lid-1",
        "kind": "lid",
        "number": "1",
        "start": 3,
        "end": 122,
    }
    assert props["parts"] == version["parts"]
    assert props["references"][0] == {
        "kind": "extref",
        "bwb_id": "BWBR0001854",
        "article": "287",
        "doc": "jci1.3:c:BWBR0001854&artikel=287",
        "text": "artikel 287, eerste lid, onder a",
        "start": 47,
        "end": 79,
        "leden": ["1"],
        "onderdelen": ["a"],
        "aanhef": False,
    }
    # The schema accepts what the builders write (unknown fields would raise).
    Node(collection="articles", type=NodeType.ARTICLE, key="k", props=props)


def test_an_article_without_structure_writes_an_empty_list_so_a_stale_one_is_replaced() -> (
    None
):
    article = _article("<artikel><kop><nr>5</nr></kop><al>Tekst.</al></artikel>")

    assert article_props(article, "BWBR0000001", None, 0)["parts"] == []
