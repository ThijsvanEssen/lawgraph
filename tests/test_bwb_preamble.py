"""The aanhef of a BWB regulation as a text with its links (recorded fixtures)."""

from __future__ import annotations

from lawgraph.core.bwb_xml import instrument_props, parse_toestand, preamble_props
from tests.paths import fixture_text

# Regeling cyberbeveiliging EZK, toestand 2026-08-15
CYBER = "bwb_regeling_cyberbeveiliging_ezk_toestand.xml"


def test_the_aanhef_of_a_regulation_is_a_text_a_block_a_part() -> None:
    preamble = parse_toestand(fixture_text(CYBER)).preamble

    assert preamble is not None
    lines = preamble.text.split("\n")
    assert lines[0].startswith("De Staatssecretaris van Economische Zaken en Klimaat,")
    assert lines[1:] == [
        "Gelet op de artikelen 19, 23, eerste lid, en 28 van het "
        "Cyberbeveiligingsbesluit;",
        "Besluit:",
    ]
    assert [
        (part.kind, preamble.text[part.start : part.end]) for part in preamble.parts
    ] == [
        ("wie", lines[0]),
        ("considerans", lines[1]),
        ("gelet_op", lines[1]),
        ("afkondiging", "Besluit:"),
    ]


def test_the_links_of_the_considerans_name_their_articles() -> None:
    props = preamble_props(parse_toestand(fixture_text(CYBER)).preamble)

    assert props is not None
    text = props["text"]
    assert [
        (text[ref["start"] : ref["end"]], ref["bwb_id"], ref["article"], ref["leden"])
        for ref in props["references"]
    ] == [
        ("artikelen 19", "BWBR0052875", "19", []),
        ("23, eerste lid", "BWBR0052875", "23", ["1"]),
        ("28 van het Cyberbeveiligingsbesluit", "BWBR0052875", "28", []),
    ]


def test_the_aanhef_of_a_law_keeps_every_paragraph_on_a_line() -> None:
    preamble = parse_toestand(fixture_text("bwb_uavg_toestand.xml")).preamble

    assert preamble is not None
    assert [part.kind for part in preamble.parts] == [
        "wij",
        "considerans",
        "gelet_op",
        "afkondiging",
    ]
    considerans, gelet_op = preamble.parts[1:3]
    basis = "Gelet op artikel 10, tweede en derde lid, van de Grondwet;"
    assert preamble.text[considerans.start : considerans.end].split("\n")[-1] == basis
    assert preamble.text[gelet_op.start : gelet_op.end] == basis
    assert preamble.text.endswith("gelijk Wij goedvinden en verstaan bij deze:")


def test_a_regulation_without_an_aanhef_has_no_preamble() -> None:
    xml = """<toestand bwb-id="BWBR0000001"><wetgeving soort="wet"><wet-besluit>
      <wettekst><artikel><kop><nr>1</nr></kop><al>Tekst.</al></artikel></wettekst>
      </wet-besluit></wetgeving></toestand>"""

    toestand = parse_toestand(xml)

    assert toestand.preamble is None
    # always written: a preamble that is gone must not linger in the merged props
    props = instrument_props(toestand, "BWBR0000001")
    assert "preamble" in props
    assert props["preamble"] is None


def test_a_list_in_the_considerans_is_a_line_an_item() -> None:
    xml = """<toestand bwb-id="BWBR0000002"><wetgeving><regeling><aanhef>
      <wie>De Minister,</wie>
      <considerans><considerans.al>Overwegende:</considerans.al>
        <lijst><li><li.nr>a.</li.nr><al>dat het moet;</al></li>
        <li><li.nr>b.</li.nr><al>dat het kan;</al></li></lijst></considerans>
      <meta-data><brondata/></meta-data></aanhef></regeling></wetgeving></toestand>"""

    preamble = parse_toestand(xml).preamble

    assert preamble is not None
    assert preamble.text == (
        "De Minister,\nOverwegende:\na. dat het moet;\nb. dat het kan;"
    )
