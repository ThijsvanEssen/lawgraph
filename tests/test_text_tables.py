"""Tables in the text of a Kamerstuk and of a paragraph of a judgment: a row a line, its cells
separated by a tab, and the table a span of the text (``core.text_tables.TextTable``), as in
the text of an article (``tests/test_bwb_tables.py``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest

from lawgraph.api.schemas.documents import DocumentTextResponse
from lawgraph.api.schemas.judgments import JudgmentDTO
from lawgraph.core.document_xml import ParsedDocument, parse_document_xml
from lawgraph.core.judgment_metadata import parse_judgment
from lawgraph.core.judgment_paragraphs import judgment_text
from lawgraph.core.props import DocumentProps, JudgmentParagraphProps
from lawgraph.core.text_tables import CellSpan, TextTable, lay_out
from lawgraph.pipelines.normalize.tk_content import document_props
from tests.paths import fixture_text

MVT = "Memorie van toelichting"


def _document(name: str) -> ParsedDocument:
    return parse_document_xml(fixture_text(f"{name}.xml"))


def _rows(text: str, table: TextTable | dict[str, Any]) -> list[list[str]]:
    start, end = (
        (table.start, table.end)
        if isinstance(table, TextTable)
        else (table["start"], table["end"])
    )
    return [row.split("\t") for row in text[start:end].split("\n")]


def _paragraph(name: str, paragraph_id: str) -> dict[str, Any]:
    paragraphs, _ = judgment_text(parse_judgment(fixture_text(f"{name}.xml")))
    return next(p for p in paragraphs if p["id"] == paragraph_id)


# ── Kamerstukken ─────────────────────────────────────────────────────────────


def test_a_table_of_a_kamerstuk_is_a_span_of_its_text() -> None:
    """kst-33478-3: a transposition table whose first cell spans two rows ("I. 1")."""
    parsed = _document("kst_33478_3")
    (table,) = parsed.tables
    rows = _rows(parsed.text, table)
    assert rows[0] == [
        "I. 1",
        "Landen dienen te beschikken over de juridische mogelijkheden om daders van het "
        "financieren van terrorisme te vervolgen en te bestraffen.",
        "Algemeen van aard.",
    ]
    assert rows[1] == [  # next to the cell of the row above that spans it
        "Financieren van terrorisme moet een gronddelict zijn voor het misdrijf witwassen.",
        "Artikel 420bis Sr (witwassen van voorwerpen afkomstig van enig misdrijf)",
    ]
    assert rows[2] == [
        "G",
        "Voor de uitleg van Aanbeveling 5 en de Interpretive Note gelden de volgende "
        "definities:",
        "",
    ]
    assert (table.head_rows, table.columns) == (0, 3)
    assert table.spans[0] == CellSpan(row=0, cell=0, cols=1, rows=2)
    assert parsed.text[table.start - 1] == "\n"
    assert table.end == len(parsed.text) or parsed.text[table.end] == "\n"


def test_the_header_of_a_table_of_a_kamerstuk_is_its_thead() -> None:
    parsed = _document("kst_35470_xiv_4")
    table = parsed.tables[0]
    rows = _rows(parsed.text, table)
    assert (table.head_rows, table.columns) == (1, 3)
    assert rows[:2] == [
        [
            "Omvang begrotingsartikel (stand ontwerp-begroting) in € miljoen",
            "Beleidsmatige mutaties (ondergrens in € miljoen)",
            "Technische mutaties (ondergrens in € miljoen)",
        ],
        ["< 50", "1", "2"],
    ]


def test_a_cell_spanning_columns_of_a_kamerstuk() -> None:
    parsed = _document("kst_34986_3_excerpt")
    table = parsed.tables[0]  # of the Waterwet
    rows = _rows(parsed.text, table)
    assert rows[1] == ["Hoofdstuk 1 Algemene bepalingen"]
    assert CellSpan(row=1, cell=0, cols=4, rows=1) in table.spans
    assert (table.head_rows, table.columns) == (1, 4)


def test_normalize_tk_content_keeps_the_tables() -> None:
    props = document_props(_document("kst_33478_3"), kind=MVT)
    DocumentProps.model_validate(props)
    (table,) = props["tables"]
    assert table["spans"][0] == {"row": 0, "cell": 0, "cols": 1, "rows": 2}
    assert document_props(_document("kst_31911_3"), kind=MVT)["tables"] is None


def test_the_paper_serves_its_tables() -> None:
    parsed = _document("kst_33478_3")
    paper = DocumentTextResponse.from_document(
        {"key": "p", "id": "documents/p", "props": document_props(parsed, kind=MVT)}
    )
    (table,) = paper.tables
    assert (table.start, table.end) == (parsed.tables[0].start, parsed.tables[0].end)
    assert table.spans[0].rows == 2
    beyond = {
        "text": "a\tb",
        "tables": [{"start": 0, "end": 9, "head_rows": 0, "columns": 2}],
    }
    assert (
        DocumentTextResponse.from_document(
            {"key": "p", "id": "documents/p", "props": beyond}
        ).tables
        == []
    )


# ── judgments ────────────────────────────────────────────────────────────────


def test_a_table_in_a_numbered_consideration_is_a_span_of_its_text() -> None:
    """ECLI:NL:GHAMS:2025:118, r.o. 5.12: the costs, after the sentence that names them."""
    paragraph = _paragraph("rechtspraak_ghams_2025_118", "rov-5.12")
    (table,) = paragraph["tables"]
    text = paragraph["text"]
    assert text[: table["start"]].endswith("worden begroot op:\n\n")
    assert table["end"] == len(text)
    assert _rows(text, table) == [
        ["- griffierecht", "€", "349,00", ""],
        ["- salaris advocaat", "€", "7.144,00", "(2 punten × € 3.572,00)"],
        [
            "- nakosten",
            "€",
            "178,00",
            "(plus de verhoging zoals vermeld in de beslissing)",
        ],
        ["Totaal", "€", "7.671,00", ""],
    ]
    assert table == {
        "start": table["start"],
        "end": table["end"],
        "head_rows": 0,
        "columns": 4,
    }
    JudgmentParagraphProps.model_validate(paragraph)


def test_cells_of_a_judgment_that_span_rows() -> None:
    """ECLI:NL:RBZWB:2019:1062, r.o. 2.5: six headings span two rows, next to "Jaar 2013";
    a cell of two paragraphs ("Tijd-", "vak") is one line."""
    paragraph = _paragraph("rechtspraak_rbzwb_2019_1062", "rov-2.5")
    (table,) = paragraph["tables"]
    rows = _rows(paragraph["text"], table)
    assert rows[0] == [
        "Periode van – tot en met",
        "Tijd- vak",
        "Loonheffingen",
        "Verzuim-boete",
        "Kosten",
        "Betaling / verrekening",
        "Onbetaald",
    ]
    assert rows[1] == ["Jaar 2013"]
    assert rows[2] == [
        "9 sept - 6 okt",
        "10",
        "€ 233.060",
        "€ 2.146",
        "-",
        "-/- € 18.496",
        "€ 216.710",
    ]
    assert rows[6] == ["Jaar 2014", "", "", "", "", "", ""]
    assert table["columns"] == 7
    assert table["spans"] == [
        {"row": 0, "cell": c, "cols": 1, "rows": 2} for c in range(1, 7)
    ]


def test_the_empty_rows_a_court_sets_under_its_signature_are_left_out() -> None:
    """ECLI:NL:RBZWB:2026:1134: a table of one line over three columns and four empty rows."""
    paragraph = _paragraph("rechtspraak_rbzwb_2026_1134", "rov-4.4")
    (table,) = paragraph["tables"]
    assert paragraph["text"][table["start"] : table["end"]].startswith(
        "Deze beschikking is gegeven door mr. Haerkens-Wouters"
    )
    assert "\n" not in paragraph["text"][table["start"] : table["end"]]
    assert table["spans"] == [{"row": 0, "cell": 0, "cols": 3, "rows": 1}]


def test_a_table_that_stands_on_its_own_is_a_paragraph_of_its_own() -> None:
    paragraphs, _ = judgment_text(
        parse_judgment(fixture_text("rechtspraak_rbrot_2022_10632.xml"))
    )
    (paragraph,) = [p for p in paragraphs if p.get("tables")]
    assert (paragraph["number"], paragraph["kind"]) == (None, "body")
    assert paragraph["text"] == "griffier\trechter"
    assert paragraph["tables"] == [
        {"start": 0, "end": 16, "head_rows": 0, "columns": 2}
    ]


def test_a_paragraph_serves_its_tables() -> None:
    paragraph = _paragraph("rechtspraak_ghams_2025_118", "rov-5.12")
    judgment = JudgmentDTO.from_document(
        {"id": "judgments/j", "key": "j", "props": {"paragraphs": [paragraph]}}
    )
    (served,) = judgment.paragraphs
    (table,) = served.tables
    assert (table.start, table.end, table.columns) == (
        paragraph["tables"][0]["start"],
        len(paragraph["text"]),
        4,
    )


# ── the layout ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # an empty row under a cell spanning three rows: the cell spans the two left
        (
            '<row><entry morerows="2">a</entry><entry>b</entry></row>'
            "<row><entry/></row><row><entry>c</entry></row>",
            ([["a", "b"], ["c"]], (CellSpan(0, 0, 1, 2),)),
        ),
        # a row all of whose columns cells above it span: no line of its own
        (
            '<row><entry morerows="1">a</entry><entry morerows="1">b</entry></row><row/>'
            "<row><entry>c</entry><entry>d</entry></row>",
            ([["a", "b"], ["c", "d"]], ()),
        ),
    ],
)
def test_an_empty_row_is_left_out(rows: str, expected: tuple[Any, Any]) -> None:
    xml = f'<table><tgroup cols="2"><tbody>{rows}</tbody></tgroup></table>'
    laid = lay_out(ET.fromstring(xml), lambda entry: (entry.text or "").strip())
    assert laid is not None
    cals, cells = laid
    assert (cells, cals.text_table(0, 1).spans) == expected


def test_a_table_without_text_is_none() -> None:
    xml = "<table><tgroup><tbody><row><entry/><entry/></row></tbody></tgroup></table>"
    assert lay_out(ET.fromstring(xml), lambda entry: entry.text or "") is None
