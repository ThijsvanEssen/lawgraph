"""Unit tests for annex reference detection and XML extraction."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.config.constants import SCOPE_TYPE_DISCRETIONARY, SCOPE_TYPE_FIXED
from lawgraph.core.annex_xml import annex_node_key, annex_props, parse_annexes
from lawgraph.pipelines.semantic._annex_detect import (
    annex_name,
    detect_annex_name,
    detect_annex_references,
)
from lawgraph.pipelines.semantic.bwb_annexes import BWBAnnexesSemanticPipeline


class _DummyStore:
    pass


def _pipeline() -> BWBAnnexesSemanticPipeline:
    return BWBAnnexesSemanticPipeline(store=_DummyStore())


# ── text detection ───────────────────────────────────────────────────────────


def test_detects_roman_numeral_label():
    hits = detect_annex_references(
        "De sectoren, vermeld in bijlage I, vallen onder deze wet."
    )
    assert len(hits) == 1
    assert hits[0].label == "I"
    assert hits[0].scope_type == SCOPE_TYPE_FIXED


def test_detects_numeric_label():
    hits = detect_annex_references("zoals opgenomen in bijlage 2 bij deze regeling")
    assert len(hits) == 1
    assert hits[0].label == "2"


def test_unlabelled_annex():
    hits = detect_annex_references("De stoffen genoemd in de bijlage zijn verboden.")
    assert len(hits) == 1
    assert hits[0].label is None


def test_discretionary_scope_detected():
    text = (
        "De sectoren vermeld in bijlage I. Bij ministeriële regeling kunnen "
        "sectoren aan bijlage I worden toegevoegd."
    )
    hits = detect_annex_references(text)
    assert hits[0].scope_type == SCOPE_TYPE_DISCRETIONARY


def test_deduplicates_labels():
    text = "bijlage I geldt, en bijlage I geldt nogmaals, naast bijlage II"
    labels = [h.label for h in detect_annex_references(text)]
    assert labels == ["I", "II"]


def test_empty_text():
    assert detect_annex_references("") == []


def test_the_name_of_an_annex_is_its_title_without_the_articles_it_belongs_to():
    title = "Bevoegdheidsregeling bestuursrechtspraak (artikelen 8:5, 8:6 en 8:7)"
    assert annex_name(title) == "Bevoegdheidsregeling bestuursrechtspraak"
    assert annex_name("Tabel") is None  # one word is no name to look for
    assert annex_name(None) is None


def test_an_article_names_an_annex_by_its_name():
    text = "een besluit als bedoeld in artikel 1 van de bij deze wet behorende Regeling x y."
    hit = detect_annex_name(text, "Regeling x y")
    assert hit is not None and text[hit.start : hit.end] == "Regeling x y"
    assert detect_annex_name("De Regeling x yz.", "Regeling x y") is None


def test_node_key_is_deterministic():
    assert annex_node_key("BWBR0001854", "I") == "bwbr0001854_annex_i"
    assert annex_node_key("BWBR0001854", None) == "bwbr0001854_annex"


# ── XML extraction ───────────────────────────────────────────────────────────

_ANNEX_XML = """
<regeling>
  <bijlage label="bijlage">
    <kop><nr>I</nr><titel>Vitale sectoren</titel></kop>
    <al>De volgende sectoren worden aangemerkt als vitaal.</al>
    <lijst>
      <li><al>Telecommunicatie</al></li>
      <li><al>Energie</al></li>
      <li><al>Drinkwater</al></li>
    </lijst>
  </bijlage>
</regeling>
"""


def test_an_annex_is_parsed_with_its_label_title_entries_and_description():
    (annex,) = parse_annexes(ET.fromstring(_ANNEX_XML))
    props = annex_props(annex, "BWBR0099999")
    assert annex_node_key("BWBR0099999", annex.label) == "bwbr0099999_annex_i"
    assert props["label"] == "I"
    assert props["title"] == props["display_name"] == "Vitale sectoren"
    assert [e["name"] for e in props["entries"]] == [
        "Telecommunicatie",
        "Energie",
        "Drinkwater",
    ]
    assert "vitaal" in props["description"]
    assert props["instrument_id"] == "instruments/bwbr0099999"


def test_an_annex_without_a_heading_is_the_annex_of_its_regulation():
    root = ET.fromstring("<regeling><bijlage><al>Tekst</al></bijlage></regeling>")
    (annex,) = parse_annexes(root)
    assert annex_node_key("BWBR0099999", annex.label) == "bwbr0099999_annex"
    assert annex_props(annex, "BWBR0099999")["display_name"] == "Annex"
