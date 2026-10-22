"""What ``core/publication_xml.py`` reads of the XML of an official publication."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lawgraph.core.publication_xml import publication_title, staatsblad_ref_from_bwb_xml


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_publication_title_helper() -> None:
    assert publication_title(_el("<r/>"), "fallback") == "fallback"
    assert publication_title(_el("<r><titel>T</titel></r>"), "f") == "T"
    # the masthead of the series is no title; the metadata's ``DC.title`` is
    masthead = "<r><titel>Staatsblad</titel><titel>WIJZIGING</titel></r>"
    assert publication_title(_el(masthead), "f") == "WIJZIGING"
    meta = (
        '<r><metadata><meta name="DC.title" content="Besluit van 1 mei"/></metadata>'
        "<titel>Staatsblad</titel></r>"
    )
    assert publication_title(_el(meta), "f") == "Besluit van 1 mei"
    assert publication_title(_el("<r><titel>Tractatenblad</titel></r>"), "f") == "f"


def test_extract_staatsblad_ref_from_bwb_xml() -> None:
    fn = staatsblad_ref_from_bwb_xml
    xml = "<r><publicatiejaar>2015</publicatiejaar><publicatienummer> 134 </publicatienummer></r>"
    assert fn(xml) == ("2015", "134")
    bad_year = "<r><publicatiejaar>abc</publicatiejaar><publicatienummer>1</publicatienummer></r>"
    assert fn(bad_year) is None
    assert fn('<r><x a="stb-2001-55"/></r>') == ("2001", "55")
    assert fn("<r>tekst stb-2001-56</r>") == ("2001", "56")
    assert fn("<r/>") is None
    with pytest.raises(ET.ParseError):  # kapot is not "no Staatsblad"
        fn("<bad")
    # BWB writes publicatienr; of its publications, the one that made the regulation
    bwb = (
        '<toestand><brondata><oorspronkelijk><publicatie effect="wijziging" soort="Stb">'
        "<publicatiejaar>2019</publicatiejaar><publicatienr>7</publicatienr></publicatie>"
        '<publicatie effect="nieuwe-regeling" soort="Stb" urlidentifier="">'
        "<publicatiejaar>1931</publicatiejaar><publicatienr>248</publicatienr></publicatie>"
        '<publicatie soort="Stcrt"><publicatiejaar>1931</publicatiejaar>'
        "<publicatienr>99</publicatienr></publicatie>"
        "</oorspronkelijk></brondata></toestand>"
    )
    assert fn(bwb) == ("1931", "248")
    # a treaty: its Tractatenblad names no Staatsblad of the same year and number
    trb = (
        '<toestand><brondata><oorspronkelijk><publicatie soort="Trb">'
        "<publicatiejaar>2018</publicatiejaar><publicatienr>100</publicatienr>"
        "</publicatie></oorspronkelijk></brondata></toestand>"
    )
    assert fn(trb) is None


def test_a_publication_is_titled_by_its_intitule_not_its_first_heading() -> None:
    # the Staatsblad of a law: masthead, intitule, then the headings of its text in capitals
    root = ET.parse(Path(__file__).parent / "fixtures" / "stb_2026_56_excerpt.xml")
    assert publication_title(root.getroot(), "f") == (
        "Wet van 25 februari 2026 tot vaststelling van het nieuwe Wetboek van "
        "Strafvordering (Wetboek van Strafvordering)"
    )
