"""The transposition table of the new Wetboek van Strafvordering, read from its PDF: four pages
of blg-1081574 (Bijlage 1 bij de MvT 36327), the last page of the half "nieuw-huidig", the
first page of the half "huidig-nieuw", a page with lines that run on and the page with
art. 126ffa."""

from __future__ import annotations

import pytest

from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.transposition_tables import (
    OldArticle,
    pdf_pages,
    places,
    read_table,
    source_rows,
)
from tests.paths import FIXTURES

PDF = FIXTURES / "blg_1081574_excerpt.pdf"


@pytest.fixture(scope="module")
def articles() -> dict[str, OldArticle]:
    table = read_table(pdf_pages(PDF.read_bytes()))
    assert table is not None
    assert (table.old_law, table.new_law) == (
        "Wetboek van Strafvordering",
        "Wetboek van Strafvordering",
    )
    return {article.number: article for article in table.articles}


def _rows(article: OldArticle) -> list[tuple[str, str]]:
    return [(p.part, p.text) for p in article.placements]


def test_each_part_of_the_old_article_with_its_place(
    articles: dict[str, OldArticle],
) -> None:
    assert _rows(articles["126ffa"]) == [
        ("1", "2.8.6, 1"),
        ("2", "2.8.6, 1"),
        ("2 a", "Besluit B2"),
        ("2 b", "Besluit B2"),
        ("3", "2.8.6, 1"),
        ("4", "2.8.6, 2"),
    ]
    assert articles["126ffa"].page == 4


def test_a_whole_article_and_its_onderdelen_without_a_lid(
    articles: dict[str, OldArticle],
) -> None:
    assert _rows(articles["1"]) == [("", "1.1.1")]
    assert _rows(articles["126ee"])[:2] == [("", "2.8.4"), ("a", "2.8.4, a")]


def test_a_line_without_a_label_belongs_to_the_part_before_it(
    articles: dict[str, OldArticle],
) -> None:
    assert _rows(articles["2"])[:3] == [
        ("1", "1.2.9, 1"),
        ("1", "1.2.9, 1, a"),
        ("1", "1.2.9, 1, b"),
    ]
    assert ("2", "vervallen (mvt)") in _rows(articles["2"])


def test_a_line_that_runs_on_is_one_row(articles: dict[str, OldArticle]) -> None:
    assert _rows(articles["126ue"])[0] == (
        "1",
        "2.7.49; 2.7.2; 2.7.46; 2.7.53, a; algemene regeling 2.1.9; Besluit B2",
    )
    assert _rows(articles["126uf"])[1] == (
        "2",
        "2.7.2; 2.7.46, 2; 2.7.44; 2.7.56; Besluit B2; algemene regeling 2.1.13",
    )


def test_headings_and_the_half_nieuw_huidig_are_no_rows(
    articles: dict[str, OldArticle],
) -> None:
    # a heading over two lines ends the article before it
    assert _rows(articles["126bb"])[-1] == ("5", "2.7.36, 1")
    assert _rows(articles["126dd"])[-1] == ("2", "bepaling over gegevensverwerking")
    # page 1 of the excerpt is of the other half: its numbers are of the new law
    assert not any("." in number for number in articles)
    assert articles["1"].page == 2


def test_another_document_is_no_table() -> None:
    assert read_table(["Memorie van toelichting", "Artikel 1\n1.1.1"]) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2.8.6, 1", [Place("2.8.6, 1", "2.8.6", ("1",))]),
        ("2.8.4", [Place("2.8.4", "2.8.4", ())]),
        (
            "2.9.1, 2; 2.8.22; 2.7.53",
            [
                Place("2.9.1, 2", "2.9.1", ("2",)),
                Place("2.8.22", "2.8.22", ()),
                Place("2.7.53", "2.7.53", ()),
            ],
        ),
        ("2.8.2, 2, a", [Place("2.8.2, 2, a", "2.8.2", ("2",))]),
        (
            "4.3.30, 2, 3, 4 en 5",
            [Place("4.3.30, 2, 3, 4 en 5", "4.3.30", ("2", "3", "4", "5"))],
        ),
        ("2.7.3, 1, c, en 2", [Place("2.7.3, 1, c, en 2", "2.7.3", ("1", "2"))]),
        ("4.5.3, 2, d, 1°", [Place("4.5.3, 2, d, 1°", "4.5.3", ("2",))]),
        ("1.2.24, 1 en", [Place("1.2.24, 1 en", "1.2.24", ("1",))]),
        (
            "algemene regeling (1.4.8)",
            [Place("algemene regeling (1.4.8)", "1.4.8", (), general=True)],
        ),
        (
            "algemene regeling 2.1.10",
            [Place("algemene regeling 2.1.10", "2.1.10", (), general=True)],
        ),
        ("Besluit B2", [Place("Besluit B2", None, ())]),
        ("vervallen (mvt)", [Place("vervallen (mvt)", None, ())]),
        (
            "2.7.49, 4; Besluit B2",
            [Place("2.7.49, 4", "2.7.49", ("4",)), Place("Besluit B2", None, ())],
        ),
        ("1,5,2, 6", [Place("1,5,2, 6", None, (), readable=False)]),
        ("**", [Place("**", None, (), readable=False)]),
        (
            "algemene regeling (1.2.6 en 1.2.7)",
            [Place("algemene regeling (1.2.6 en 1.2.7)", None, (), readable=False)],
        ),
        ("2.8.6, 1, 1e zin", [Place("2.8.6, 1, 1e zin", "2.8.6", ("1",))]),
        ("2.8.6, ab cd", [Place("2.8.6, ab cd", None, (), readable=False)]),
    ],
)
def test_the_places_a_row_gives(text: str, expected: list[Place]) -> None:
    assert places(text) == expected


def test_each_place_is_a_row_of_the_source() -> None:
    table = read_table(pdf_pages(PDF.read_bytes()))
    assert table is not None
    rows = [r for r in source_rows(table) if r.old_article == "126ffa"]
    assert rows[2] == SourceRow("126ffa", "2 a", Place("Besluit B2", None, ()), "p. 4")
    assert [(r.part, r.place.article) for r in rows] == [
        ("1", "2.8.6"),
        ("2", "2.8.6"),
        ("2 a", None),
        ("2 b", None),
        ("3", "2.8.6"),
        ("4", "2.8.6"),
    ]
