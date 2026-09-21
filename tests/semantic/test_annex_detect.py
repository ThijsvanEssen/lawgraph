"""Unit tests for annex reference detection and XML extraction."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.config.constants import SCOPE_TYPE_DISCRETIONARY, SCOPE_TYPE_FIXED
from lawgraph.pipelines.semantic._annex_detect import detect_annex_references
from lawgraph.pipelines.semantic.bwb_annexes import (
    BWBAnnexesSemanticPipeline,
    annex_node_key,
)


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


def test_build_annex_node_from_xml():
    root = ET.fromstring(_ANNEX_XML)
    element = next(el for el in root.iter() if el.tag == "bijlage")
    node = _pipeline()._build_annex_node("BWBR0099999", element)
    assert node is not None
    assert node.key == "bwbr0099999_annex_i"
    assert node.props["label"] == "I"
    assert node.props["title"] == "Vitale sectoren"
    assert node.props["display_name"] == "Vitale sectoren"
    entry_names = [e["name"] for e in node.props["entries"]]
    assert entry_names == ["Telecommunicatie", "Energie", "Drinkwater"]
    assert "vitaal" in node.props["description"]


def test_build_annex_node_without_kop():
    root = ET.fromstring("<regeling><bijlage><al>Tekst</al></bijlage></regeling>")
    element = next(el for el in root.iter() if el.tag == "bijlage")
    node = _pipeline()._build_annex_node("BWBR0099999", element)
    assert node is not None
    assert node.key == "bwbr0099999_annex"
    assert node.props["display_name"] == "Annex"
