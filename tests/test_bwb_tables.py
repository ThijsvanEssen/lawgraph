"""Tables in BWB text (CALS ``<table>``): kept in the article text as rows of cells, and
described as spans of that text (Wet IB 2001, BWBR0011353, toestand 2026-02-21)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from lawgraph.api.schemas.articles import tables_from_props
from lawgraph.core.bwb_xml import (
    ArticleXml,
    article_props,
    parse_toestand,
    table_heads,
)
from tests.paths import fixture_text


@pytest.fixture(scope="module")
def ib() -> dict[str | None, ArticleXml]:
    toestand = parse_toestand(fixture_text("bwb_ib2001_tables_toestand.xml"))
    return {article.number: article for article in toestand.articles}


def _rows(article: ArticleXml, index: int = 0) -> list[list[str]]:
    """The cells of a table, a no-break space (the source writes "€\xa012.500") a space."""
    table = article.tables[index]
    text = article.text[table.start : table.end].replace("\xa0", " ")
    return [row.split("\t") for row in text.split("\n")]


def test_a_table_in_a_lid_is_in_the_text_of_that_lid(ib) -> None:
    article = ib["3.112"]
    (table,) = article.tables
    assert _rows(article) == [
        ["meer dan", "maar niet meer dan", "op jaarbasis"],
        ["–", "€ 12.500", "nihil"],
        ["€ 12.500", "€ 25.000", "0,10% van deze waarde"],
        ["€ 25.000", "€ 50.000", "0,20% van deze waarde"],
        ["€ 50.000", "€ 75.000", "0,25% van deze waarde"],
        ["€ 75.000", "€ 1.350.000", "0,35% van deze waarde"],
        [
            "€ 1.350.000",
            "",
            "€ 4.725 vermeerderd met 2,35% van de eigenwoningwaarde voor zover deze "
            "uitgaat boven € 1.350.000",
        ],
    ]
    assert (table.head_rows, table.columns, table.spans) == (1, 3, ())
    lid = next(part for part in article.parts if part.id == "lid-1")
    assert lid.start < table.start and table.end == lid.end
    assert article.text[lid.start : table.start].endswith("eigenwoningwaarde van:\n")
    assert article.text[table.end :].startswith("\n2. De eigenwoningwaarde")


def test_a_table_before_the_next_lid_of_article_2_10(ib) -> None:
    article = ib["2.10"]
    (table,) = article.tables
    rows = _rows(article)
    assert rows[0][0].startswith("Bij een belastbaar inkomen uit werk en woning")
    assert all(len(row) <= table.columns for row in rows)
    assert "aan de hand van de volgende tabel.\n" in article.text[: table.start]
    assert article.text[table.end :].startswith("\n2. Indien")


def test_a_table_outside_the_leden_keeps_its_header_and_spanning_cell(ib) -> None:
    article = ib["2.12"]
    (table,) = article.tables
    assert _rows(article)[:3] == [
        [
            "Bij een belastbaar inkomen uit aanmerkelijk belang van meer dan",
            "maar niet meer dan",
            "bedraagt de belasting het in kolom III vermelde bedrag, vermeerderd met het "
            "bedrag dat wordt berekend door het in kolom IV vermelde percentage te nemen "
            "van het gedeelte van het belastbare inkomen uit aanmerkelijk belang dat het "
            "in kolom I vermelde bedrag te boven gaat",
        ],
        ["I", "II", "III", "IV"],
        ["–", "€ 68.843", "–", "24,5%"],
    ]
    assert (table.head_rows, table.columns) == (2, 4)
    assert [span.to_dict() for span in table.spans] == [
        {"row": 0, "cell": 2, "cols": 2, "rows": 1}
    ]


def test_the_tables_are_stored_on_the_article(ib) -> None:
    props = article_props(ib["3.112"], "BWBR0011353", "Wet inkomstenbelasting 2001", 0)
    (table,) = props["tables"]
    assert set(table) == {"start", "end", "head_rows", "columns"}
    assert "op jaarbasis" in props["text"][table["start"] : table["end"]]
    assert "tables" not in article_props(replace(ib["3.112"], tables=()), "B", None, 0)


def _article(xml: str) -> ArticleXml:
    (article,) = parse_toestand(
        f"<toestand bwb-id='BWBR0000001'>{xml}</toestand>"
    ).articles
    return article


def test_a_table_in_an_onderdeel_stays_in_that_onderdeel() -> None:
    article = _article(
        "<artikel label='Artikel 1'><kop><nr>1</nr></kop><lid><lidnr>1</lidnr>"
        "<al>Het tarief is:</al><lijst><li><li.nr>a.</li.nr><al>voor een woning:</al>"
        "<table><tgroup cols='2'><tbody><row><entry><al>x</al></entry>"
        "<entry><al>1%</al></entry></row></tbody></tgroup></table></li>"
        "<li><li.nr>b.</li.nr><al>anders nihil.</al></li></lijst></lid></artikel>"
    )
    (table,) = article.tables
    assert article.text[table.start : table.end] == "x\t1%"
    onder_a = next(part for part in article.parts if part.id == "lid-1-onder-a")
    assert article.text[onder_a.start : onder_a.end] == "voor een woning:\nx\t1%"
    assert article.text.endswith("\nb. anders nihil.")


def test_the_api_gives_the_tables_that_fit_the_text(ib) -> None:
    props = article_props(ib["2.12"], "BWBR0011353", None, 0)
    props["tables"].append({"start": 0, "end": len(props["text"]) + 1})
    (table,) = tables_from_props(props)
    assert (table.head_rows, table.columns) == (2, 4)
    assert [span.cols for span in table.spans] == [2]


def test_the_header_of_a_table_is_its_first_rows() -> None:
    """Art. 2 Regeling aanwijzing aanbieders essentiële diensten EZK (BWBR0045077): the
    header "Sector | Aanbieder | Essentiële dienst" is the first line of the table; a list
    without a header (a specificatielijst) has none."""
    (article,) = [
        a
        for a in parse_toestand(
            fixture_text("bwb_aanbieders_ezk_toestand.xml")
        ).articles
        if a.number == "2"
    ]
    tables = [table.to_dict() for table in article.tables]
    (head,) = table_heads(article.text, tables)
    assert article.text[head[0] : head[1]] == "Sector\tAanbieder\tEssentiële dienst"
    assert table_heads("a\tb\nc\td", [{"start": 0, "end": 7, "head_rows": 0}]) == []
    assert table_heads("a\tb\nc\td", [{"start": 0, "end": 7, "head_rows": 2}]) == [
        (0, 7)
    ]
