"""Tests for the smaller shared helpers in ``lawgraph.core`` and their call sites."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.core import aliases
from lawgraph.core import xml as core_xml
from lawgraph.core.publication_xml import publication_title


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_collapse_ws_and_text_of() -> None:
    assert core_xml.collapse_ws(" a \n b\t c ") == "a b c"
    assert core_xml.collapse_ws("") == ""
    assert core_xml.collapse_ws(None) == ""
    assert core_xml.text_of(None) == ""
    assert core_xml.text_of(None, " ") == ""
    element = _el("<p>a<b>b</b>c</p>")
    assert core_xml.text_of(element) == "abc"
    assert core_xml.text_of(element, " ") == "a b c"


def test_first_named_and_find_own_text() -> None:
    root = _el("<r><a>1</a><b>2</b></r>")
    first = core_xml.first_named(root, "b", "a")
    assert first is not None and first.tag == "a"
    assert core_xml.first_named(root, "z") is None
    assert core_xml.find_own_text(root, "z") is None


def test_publication_title_helper() -> None:
    assert publication_title(_el("<r/>"), "fallback") == "fallback"
    assert publication_title(_el("<r><titel>T</titel></r>"), "f") == "T"


def test_normalize_instrument_id() -> None:
    assert aliases.normalize_instrument_id(" bwbr1 ") == "BWBR1"
    assert aliases.normalize_instrument_id(None) is None
    assert aliases.normalize_instrument_id("") is None


def test_the_gaps_report_names_a_law_from_its_sru_record_without_downloading_it(
    monkeypatch,
) -> None:
    """The report needs a name; the toestand is the whole law, fetched by the gaps run."""
    from lawgraph.commands import gaps

    titles = {"BWBR1": "Wet op X", "BWBR2": None}

    class _FakeClient:
        def latest_toestand(self, bwb_id: str) -> dict | None:
            if bwb_id == "BWBR3":
                raise RuntimeError("SRU error")
            return {"bwb_id": bwb_id, "title": titles[bwb_id]}

        def fetch_toestand_xml(self, meta: dict) -> str:
            raise AssertionError("the toestand is not needed for a name")

    monkeypatch.setattr(gaps, "BWBClient", _FakeClient)
    result = gaps._resolve_names_from_bwb(
        ["BWBR1", "BWBR2", "BWBR3"], {"BWBR9": "Bekend"}
    )
    assert result == {"BWBR9": "Bekend", "BWBR1": "Wet op X"}
