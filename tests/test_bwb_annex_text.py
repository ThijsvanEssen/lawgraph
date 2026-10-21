"""The text of an annex as that of an article: its paragraphs, its tables, its headings and
its links (``core.bwb_xml.parse_annexes``), on the annexes of the Cyberbeveiligingswet
(BWBR0052872, toestand 2026-08-15): a table of sectors under "Bijlage 1" with its footnotes."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from lawgraph.api.schemas.tables import tables_from_props
from lawgraph.core.bwb_xml import (
    AnnexXml,
    annex_keys,
    annex_props,
    parse_annexes,
    parse_toestand,
)
from tests.asserts import show_items
from tests.paths import fixture_text

CBW = "BWBR0052872"


@pytest.fixture(scope="module")
def cbw() -> tuple[AnnexXml, ...]:
    return parse_toestand(fixture_text("bwb_cbw_annexes_toestand.xml")).annexes


def _rows(annex: AnnexXml, index: int = 0) -> list[list[str]]:
    table = annex.tables[index]
    text = annex.text[table.start : table.end].replace("\xa0", " ")
    return [row.split("\t") for row in text.split("\n")]


def test_an_annex_is_named_as_its_heading_prints_it(cbw) -> None:
    assert [(a.label, a.name, a.title) for a in cbw] == [
        ("1", "Bijlage 1", None),
        ("2", "Bijlage 2", None),
    ]


def test_the_table_of_an_annex_is_a_table_of_its_text(cbw) -> None:
    annex = cbw[0]
    (table,) = annex.tables
    rows = _rows(annex)
    assert rows[0] == ["Sector", "Subsector", "Soort entiteit"]
    assert rows[1][:2] == ["Energie", "Elektriciteit"]
    assert rows[1][2].startswith("– Elektriciteitsbedrijven als bedoeld in artikel 2")
    # the rows next to a cell spanning rows have fewer cells
    assert rows[2] == [
        "– Distributiesysteembeheerders als bedoeld in artikel 2, onderdeel 29, van "
        "Richtlijn (EU) 2019/944"
    ]
    assert (table.head_rows, table.columns) == (1, 3)
    assert (table.spans[0].row, table.spans[0].cell, table.spans[0].rows) == (1, 0, 17)
    assert (table.spans[1].row, table.spans[1].cell, table.spans[1].rows) == (1, 1, 5)
    assert table.start == 0


def test_the_paragraphs_after_the_table_are_lines_of_their_own(cbw) -> None:
    annex = cbw[0]
    (table,) = annex.tables
    lines = annex.text[table.end :].lstrip("\n").split("\n")
    # its footnotes, each a paragraph on one line: the layout of the XML is no line break
    assert len(lines) == 22
    assert lines[0].startswith("1 Richtlijn (EU) 2019/944 van het Europees Parlement")
    assert lines[-1].startswith("22 Richtlijn 91/271/EEG van de Raad")


def test_the_links_of_an_annex_are_its_references(cbw) -> None:
    annex = cbw[0]
    celex = {ref.celex for ref in annex.references}
    assert {"32019L0944", "32019R0943", "32018L2001"} <= celex
    failing = [r for r in annex.references if annex.text[r.start : r.end] != r.text]
    assert not failing, show_items(failing)


def test_the_props_of_an_annex_hold_its_text_as_an_article_does(cbw) -> None:
    toestand = parse_toestand(fixture_text("bwb_cbw_annexes_toestand.xml"))
    props = annex_props(
        cbw[0], CBW, "Cyberbeveiligingswet", 0, annexes=annex_keys(toestand, CBW)
    )
    assert props["display_name"] == "Bijlage 1"
    assert props["position"] == 0
    assert props["text"] == cbw[0].text
    (table,) = tables_from_props(props)
    assert (table.head_rows, table.columns) == (1, 3)
    failing = [ref for ref in props["references"] if not ref.get("celex")]
    assert props["references"] and not failing, show_items(failing)


def _annexes(xml: str) -> tuple[AnnexXml, ...]:
    return parse_annexes(ET.fromstring(xml))


def test_a_list_annex_is_named_lijst_and_its_divisions_are_headings() -> None:
    """Lijst Ia of the Opiumwet (BWBR0001941): a bijlage whose heading is "Lijst", its
    divisions each a heading of its text."""
    (annex,) = _annexes(
        '<wetgeving><bijlage bwb-ng-variabel-deel="/BijlageIa" label="Lijst Ia">'
        "<kop><label>Lijst</label><nr>Ia</nr></kop>"
        '<divisie bwb-ng-variabel-deel="/BijlageIa/Divisie1"><kop><nr>1</nr>'
        "<titel>Stofgroep: Substanties die zijn afgeleid van 2-fenethylamine</titel></kop>"
        "<al>Een substantie afgeleid van 2-fenethylamine is elke chemische substantie.</al>"
        '<divisie bwb-ng-variabel-deel="/BijlageIa/Divisie1/Divisie1.1"><kop><nr>1.1</nr>'
        "<titel>Structuurelement A</titel></kop>"
        "<al>Voor structuurelement A zijn de volgende ringsystemen opgenomen:</al>"
        "</divisie></divisie></bijlage></wetgeving>"
    )
    assert (annex.label, annex.name) == ("Ia", "Lijst Ia")
    assert annex.text.split("\n") == [
        "1 Stofgroep: Substanties die zijn afgeleid van 2-fenethylamine",
        "Een substantie afgeleid van 2-fenethylamine is elke chemische substantie.",
        "1.1 Structuurelement A",
        "Voor structuurelement A zijn de volgende ringsystemen opgenomen:",
    ]
    assert [annex.text[h.start : h.end] for h in annex.headings] == [
        "1 Stofgroep: Substanties die zijn afgeleid van 2-fenethylamine",
        "1.1 Structuurelement A",
    ]


def test_the_articles_of_an_annex_are_not_its_text() -> None:
    """Bijlage 2 of the Awb holds articles: each is a node of its own, so the text of the
    annex is what stands outside them."""
    (annex,) = _annexes(fixture_text("bwb_awb_annexes_toestand.xml"))
    assert annex.name == "Bijlage 2"
    assert annex.title is not None
    assert annex.title.startswith("Bevoegdheidsregeling bestuursrechtspraak")
    assert "Winkeltijdenwet" not in annex.text


def test_an_annex_without_a_heading_is_the_bijlage_of_its_regulation() -> None:
    (annex,) = _annexes("<regeling><bijlage><al>Tekst</al></bijlage></regeling>")
    assert (annex.label, annex.name, annex.text) == (None, "Bijlage", "Tekst")
