"""The detectors of the Tweede Kamer linkers on the text ``normalize tk-content`` writes.

That text has one line per heading, paragraph, list item and table row and no whitespace
inside a line, where the flattened text before it ran on with the indentation of the XML.
"""

from __future__ import annotations

from lawgraph.core.citations import strip_xml
from lawgraph.core.document_xml import parse_document_xml
from lawgraph.core.tk_records.kinds import KIND_BILL
from lawgraph.pipelines.normalize.tk_content import document_props
from lawgraph.pipelines.semantic.tk import NamedActs, detect_tk_citations
from lawgraph.pipelines.semantic.tk_amendment_articles import (
    amendments_per_law,
    detect_amendment_citations,
)
from tests.paths import fixture_text

_DOCUMENT = """<kamerwrk><body><stuk>
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
    text = parse_document_xml(_DOCUMENT).text
    hits = {
        (hit.article_number, hit.relation)
        for hit in detect_amendment_citations(strip_xml(text))
    }
    assert hits == {
        ("36f", "REPEALS"),
        ("5", "AMENDS"),
        ("5a", "INTRODUCES"),
    }


def test_the_line_breaks_of_a_real_paper_change_no_amendment_hit() -> None:
    xml = fixture_text("kst_24507_3.xml")
    text = parse_document_xml(xml).text
    assert "\n" in text  # the paper is lines now
    assert detect_amendment_citations(strip_xml(text)) == detect_amendment_citations(
        strip_xml(text.replace("\n", " "))
    )


def test_a_citation_is_found_in_a_paragraph_and_in_a_list_item() -> None:
    text = parse_document_xml(
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


WFT, WTA = "BWBR0020368", "BWBR0019079"
_NAMES = NamedActs(
    {
        "Wet op het financieel toezicht": (WFT, None),
        "Wet toezicht accountantsorganisaties": (WTA, None),
        "Huisvestingswet 2014": ("BWBR0035303", None),
        "Woningwet": ("BWBR0005181", None),
    }
)

_TWO_LAWS = """<kamerwrk><body><stuk>
<al>Alzo Wij in overweging genomen hebben dat het wenselijk is de Wet op het financieel
toezicht en de Wet toezicht accountantsorganisaties te wijzigen.</al>
<tuskop>ARTIKEL I</tuskop>
<al>De Wet op het financieel toezicht wordt als volgt gewijzigd:</al>
<tuskop>A</tuskop>
<al>Artikel 5 vervalt.</al>
<tuskop>ARTIKEL II</tuskop>
<al>De Wet toezicht accountantsorganisaties wordt als volgt gewijzigd:</al>
<al>Artikel 7 wordt als volgt gewijzigd:</al>
<tuskop>ARTIKEL III</tuskop>
<al>Deze wet treedt in werking met ingang van de dag na uitgifte. Artikel 9 vervalt.</al>
</stuk></body></kamerwrk>"""


def _per_law(xml: str, laws: list[str]) -> dict[str, set[tuple[str, str]]]:
    props = document_props(parse_document_xml(xml), kind=KIND_BILL)
    return {
        law: {(hit.article_number, hit.relation) for hit in hits}
        for law, hits in amendments_per_law(props, laws, _NAMES).items()
    }


def test_a_bill_of_one_law_changes_that_law_wherever_it_says_so() -> None:
    assert _per_law(_TWO_LAWS, [WFT]) == {
        WFT: {("5", "REPEALS"), ("7", "AMENDS"), ("9", "REPEALS")}
    }


def test_each_law_of_a_bill_gets_only_the_articles_of_its_own_part() -> None:
    """ARTIKEL I changes the Wft, ARTIKEL II the Wta; ARTIKEL III names no law."""
    assert _per_law(_TWO_LAWS, [WFT, WTA]) == {
        WFT: {("5", "REPEALS")},
        WTA: {("7", "AMENDS")},
    }


def test_the_memorandum_of_a_verzamelwet_explains_each_law_in_its_own_article() -> None:
    """Kamerstuk 34 468, nr. 3: every change it words is to the Woningwet (ARTIKEL IX), none
    to the Huisvestingswet 2014 (ARTIKEL II)."""
    xml = fixture_text("kst_34468_3.xml")
    assert _per_law(xml, ["BWBR0035303", "BWBR0005181"]) == {
        "BWBR0035303": set(),
        "BWBR0005181": {("37", "AMENDS"), ("45", "AMENDS"), ("120b", "AMENDS")},
    }
