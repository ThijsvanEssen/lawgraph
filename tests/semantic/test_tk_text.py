"""The detectors of the Tweede Kamer linkers on the text ``normalize tk-content`` writes.

That text has one line per heading, paragraph, list item and table row and no whitespace
inside a line, where the flattened text before it ran on with the indentation of the XML.
"""

from __future__ import annotations

import pathlib

from lawgraph.core.citations import strip_xml
from lawgraph.core.kamerstuk_xml import parse_kamerstuk
from lawgraph.pipelines.semantic.tk import detect_tk_citations
from lawgraph.pipelines.semantic.tk_amendment_articles import (
    detect_amendment_citations,
)

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures"

_PAPER = """<kamerwrk><body><stuk>
<tuskop letat="vet">II. ARTIKELSGEWIJZE TOELICHTING</tuskop>
<tuskop letat="vet">Artikel I</tuskop>
<tuskop letat="vet">Onderdeel A</tuskop>
<al>Artikel 36f, eerste lid, onder d, vervalt. Het gaat om de bepaling
   die in artikel 5, tweede lid, van de Wet
      bescherming persoonsgegevens (Wbp) is opgenomen.</al>
<lijst><li><li.nr>a.</li.nr><al>Artikel 5, tweede lid,
   wordt als volgt gewijzigd:</al></li></lijst>
<al>Na artikel 5 wordt een artikel 5a ingevoegd.</al>
</stuk></body></kamerwrk>"""


def test_amendment_language_is_found_in_the_text_of_a_paper() -> None:
    text = parse_kamerstuk(_PAPER).text
    hits = {
        (hit.article_number, relation)
        for hit, relation in detect_amendment_citations(strip_xml(text), "BWBR0001")
    }
    assert hits == {
        ("36f", "REPEALS"),
        ("5", "AMENDS"),
        ("5a", "INTRODUCES"),
    }


def test_the_line_breaks_of_a_real_paper_change_no_amendment_hit() -> None:
    xml = (FIXTURES / "kst_24507_3.xml").read_text(encoding="utf-8")
    text = parse_kamerstuk(xml).text
    assert "\n" in text  # the paper is lines now
    assert detect_amendment_citations(
        strip_xml(text), "BWBR0001"
    ) == detect_amendment_citations(strip_xml(text.replace("\n", " ")), "BWBR0001")


def test_a_citation_is_found_in_a_paragraph_and_in_a_list_item() -> None:
    text = parse_kamerstuk(
        "<kamerwrk><body><stuk><al>Zie artikel 287\n   Sr en verder.</al>"
        "<lijst><li><li.nr>1.</li.nr><al>artikel 302 Sr</al></li></lijst>"
        "</stuk></body></kamerwrk>"
    ).text
    assert text == "Zie artikel 287 Sr en verder.\n1. artikel 302 Sr"
    hits = detect_tk_citations(text, {"Sr": "BWBR0001854"}, {})
    assert {(h.article_number, h.bwb_id) for h in hits} == {
        ("287", "BWBR0001854"),
        ("302", "BWBR0001854"),
    }
