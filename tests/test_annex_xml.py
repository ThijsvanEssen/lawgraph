"""The heading, entries and description of an annex (``core/annex_xml.py``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from lawgraph.core import annex_xml


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_annex_kop_entries_description() -> None:
    root = _el(
        "<bijlage><kop><nr> I </nr><titel>Vitale  sectoren</titel></kop>"
        "<al>Intro   tekst.</al><al> </al><al>Twee.</al>"
        "<lijst><li><al>Energie</al></li><li>  </li><li>Water\n en  gas</li></lijst>"
        "</bijlage>"
    )
    assert annex_xml.extract_kop(root) == ("I", "Vitale sectoren")
    assert annex_xml.extract_kop(_el("<bijlage/>")) == (None, None)
    assert annex_xml.extract_kop(_el("<bijlage><kop/></bijlage>")) == (None, None)
    assert annex_xml.extract_entries(root) == [
        {"index": 0, "name": "Energie", "heading": None, "parent_index": None},
        {"index": 1, "name": "Water en gas", "heading": None, "parent_index": None},
    ]
    assert annex_xml.extract_description(root) == "Intro tekst.\nTwee."
    assert annex_xml.extract_description(_el("<bijlage/>")) is None


def test_annex_entry_and_description_caps() -> None:
    lis = "".join(f"<li>e{i}</li>" for i in range(250))
    assert len(annex_xml.extract_entries(_el(f"<b><lijst>{lis}</lijst></b>"))) == 200
    long_al = "x" * 1500
    xml = f"<b><al>{long_al}</al><al>{long_al}</al><al>{long_al}</al></b>"
    desc = annex_xml.extract_description(_el(xml))
    assert desc is not None
    assert len(desc) == 2000  # two paragraphs (>=2000 chars) then truncated
