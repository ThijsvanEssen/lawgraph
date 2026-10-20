"""The elements of a BWB article that carry text besides its paragraphs, lists and CALS
tables: a ``<tussenkop>``, the ``<title>`` of a table, a ``<specificatielijst>``, a
``<definitielijst>``, and a list item that holds only a list of its own. Real toestanden,
trimmed to the article (``tests/fixtures/bwb_text_elements.xml``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest

from lawgraph.api.schemas.articles import headings_from_props
from lawgraph.core.bwb_xml import (
    ArticleHead,
    ArticleXml,
    article_props,
    article_version_props,
)
from lawgraph.core.xml import local_name
from tests.paths import fixture_text

ARTICLES = ("artikel", "enig-artikel")


@pytest.fixture(scope="module")
def toestanden() -> dict[str | None, ET.Element]:
    root = ET.fromstring(fixture_text("bwb_text_elements.xml"))
    return {toestand.get("bwb-id"): toestand for toestand in root}


def _article(toestanden: dict[str | None, ET.Element], bwb_id: str) -> ArticleXml:
    """The one article of the trimmed toestand of *bwb_id*."""
    (element,) = (e for e in toestanden[bwb_id].iter() if local_name(e.tag) in ARTICLES)
    return ArticleHead(element, (), None).article


def _headings(article: ArticleXml) -> list[str]:
    return [article.text[h.start : h.end] for h in article.headings]


def _rows(article: ArticleXml, index: int = 0) -> list[list[str]]:
    table = article.tables[index]
    return [
        row.split("\t") for row in article.text[table.start : table.end].split("\n")
    ]


def _part(article: ArticleXml, ident: str) -> str:
    part = next(part for part in article.parts if part.id == ident)
    return article.text[part.start : part.end]


def test_a_specificatielijst_is_a_table_under_its_tussenkop(toestanden) -> None:
    # Aanpassing bedragen reis- en verblijfkosten leden Eerste Kamer: the amounts of art. 17
    # and art. 18, tweede lid, of the Wet vergoedingen leden Eerste Kamer
    article = _article(toestanden, "BWBR0007846")
    assert article.text.split("\n") == [
        "Artikel 17",
        "Vanaf 1 januari 1996 bedraagt de vergoeding van de reiskosten op jaarbasis "
        "f 7.800. (Vergoeding van autokosten van f 0,60 per kilometer op basis van 13.000 "
        "km per jaar.)",
        "Artikel 18, tweede lid",
        "Vanaf 1 januari 1996 bedraagt de vergoeding van de verblijfkosten op jaarbasis "
        "als volgt:",
        "0 km\tf 412",
        "10 km\tf 4.120",
        "75 km\tf 8.240",
        "150 km\tf 13.390.",
    ]
    assert _headings(article) == ["Artikel 17", "Artikel 18, tweede lid"]
    (table,) = article.tables
    assert (table.head_rows, table.columns, table.spans) == (0, 2, ())
    assert article.text[table.end :] == ""


def test_the_tussenkoppen_of_an_article_are_its_headings(toestanden) -> None:
    article = _article(toestanden, "BWBR0050285")  # art. 7, a regeling of the NZa
    assert _headings(article) == [
        "Inwerkingtreding/ Bekendmaking",
        "Citeertitel",
        "Ondertekening",
    ]
    lines = article.text.split("\n")
    assert lines[0] == "Inwerkingtreding/ Bekendmaking"
    assert lines[3:] == [
        "Citeertitel",
        "Deze regeling wordt aangehaald als: Regeling aanlevering declaratiegegevens door "
        "ziektekostenverzekeraars.",
        "Ondertekening",
    ]


def test_a_tussenkop_in_a_lid_stays_in_that_lid_on_a_line_of_its_own(
    toestanden,
) -> None:
    article = _article(toestanden, "BWBR0052956")  # art. 14, a beleidsregel of the NZa
    lid = _part(article, "lid-3")
    assert "(herschikkingsronde)\na. Algemeen\nAls het totale bedrag" in lid
    assert "\nb. Zzp-meerzorg\nBij de zzp-meerzorg" in lid
    assert _headings(article) == ["a. Algemeen", "b. Zzp-meerzorg"]


def test_the_title_of_a_table_is_a_heading_above_its_rows(toestanden) -> None:
    article = _article(toestanden, "BWBR0041330")  # art. 4.1252 Besluit activiteiten
    (table,) = article.tables
    assert _headings(article) == ["Tabel 4.1252 Emissiegrenswaarden"]
    assert article.text[: table.start].endswith(
        "in een steekmonster.\nTabel 4.1252 Emissiegrenswaarden\n"
    )
    assert _rows(article) == [
        ["Stof", "Emissiegrenswaarde in mg/l"],
        ["Onopgeloste stoffen", "100"],
        ["Chemisch zuurstofverbruik", "200"],
    ]
    assert table.head_rows == 1


def test_a_definitielijst_is_a_table_of_terms_and_meanings(toestanden) -> None:
    article = _article(toestanden, "BWBR0007308")  # art. 2, a regeling MRB 1994
    assert _rows(article) == [
        ["wet:", "Wet op de motorrijtuigenbelasting 1994;"],
        ["belasting:", "motorrijtuigenbelasting."],
    ]
    assert article.text.startswith("In deze regeling wordt verstaan onder:\nwet:\t")


def test_a_definitielijst_with_markers_keeps_them_and_its_inner_list(
    toestanden,
) -> None:
    article = _article(toestanden, "BWBR0011947")  # art. 1, a regeling Wet IB 2001
    rows = _rows(article)
    assert article.tables[0].columns == 3
    marker, term, meaning = next(row for row in rows if row[0] == "c.")
    assert term == "pensioenregeling:"
    assert meaning.startswith(
        "1. een pensioenregeling overeenkomstig de wettelijke bepalingen van de "
        "loonbelasting; 2. een pensioenregeling"
    )


def test_an_item_of_only_a_list_holds_that_list(toestanden) -> None:
    # Torremolinos Protocol, Annex, Regulation I/7: "(1)" holds (a) and (b)
    article = _article(toestanden, "BWBV0003251")
    assert article.text.startswith("(1)\n(a) A certificate entitled")
    onder_1 = _part(article, "onder-1")
    assert onder_1.startswith("(a) A certificate")
    assert "\n(b) When an exemption" in onder_1
    assert _part(article, "onder-1-onder-b").startswith("When an exemption")
    assert _part(article, "onder-2").startswith("The certificates referred to")


def test_an_unmarked_item_does_not_borrow_the_marker_of_its_inner_list(
    toestanden,
) -> None:
    # Beleidsregel frictiekosten 2025–2028, art. 1: a definition whose meanings are a list
    article = _article(toestanden, "BWBR0052835")
    assert "\nlandelijke publieke mediadienst:\n– landelijke" in article.text
    term = next(part for part in article.parts if part.id == "onder-_3")
    assert term.term == "landelijke publieke mediadienst"
    assert article.text[term.start : term.end].endswith("\n– NPO.")


def test_the_headings_are_stored_and_served(toestanden) -> None:
    article = _article(toestanden, "BWBR0007846")
    props = article_props(article, "BWBR0007846", None, 0)
    assert props["headings"] == [h.to_dict() for h in article.headings]
    version = article_version_props(article, "BWBR0007846", None, 0)
    assert version["headings"] == props["headings"]
    assert "headings" not in article_props(replace(article, headings=()), "B", None, 0)
    props["headings"].append({"start": 0, "end": len(props["text"]) + 1})
    served = headings_from_props(props)
    assert [props["text"][h.start : h.end] for h in served] == _headings(article)
