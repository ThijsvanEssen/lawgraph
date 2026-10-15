"""A Staatsblad and a Staatscourant publication as ``normalize`` parses it
(``normalize/_publication.py``)."""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline


class _NoStore:
    pass


def _stb(identifier: str, xml: str) -> Any:
    return StaatsbladNormalizePipeline(store=_NoStore())._parse_publication(  # type: ignore[arg-type]
        identifier, xml
    )


def _stcrt(identifier: str, xml: str) -> Any:
    return StaatscourantNormalizePipeline(store=_NoStore())._parse_publication(  # type: ignore[arg-type]
        identifier, xml
    )


def _stb_title(xml: str) -> str:
    return _stb("stb-2015-134", xml).props["title"]


def test_stb_title_precedence_and_fallback() -> None:
    assert _stb_title("<r><titel>T</titel><citeertitel>C</citeertitel></r>") == "C"
    assert (
        _stb_title("<r><titel>T</titel><officieletitel>O</officieletitel></r>") == "O"
    )
    assert (
        _stb_title("<r><titel>T</titel><officiele-titel>O2</officiele-titel></r>")
        == "O2"
    )
    assert _stb_title("<r><titel>T</titel></r>") == "T"
    assert _stb_title("<r/>") == "Staatsblad 2015/134"
    # the misspelt tag (formerly used by the BWB normalizer) is not recognised
    assert _stb_title("<r><officietitel>X</officietitel></r>") == "Staatsblad 2015/134"
    # empty matches are skipped
    assert _stb_title("<r><citeertitel> </citeertitel><titel>T</titel></r>") == "T"


def test_stb_year_number_from_identifier_or_xml() -> None:
    node = _stb("stb-2015-134", "<r/>")
    assert (node.props["year"], node.props["number"]) == ("2015", "134")
    xml = "<r><publicatiejaar>1999</publicatiejaar><publicatienummer>7</publicatienummer></r>"
    node = _stb("other", xml)
    assert (node.props["year"], node.props["number"]) == ("1999", "7")
    node = _stb("other", "<r/>")
    assert (node.props["year"], node.props["number"]) == ("", "")
    assert node.props["title"] == "Staatsblad /"


def test_stb_nvt_text_extraction_uses_space_join_and_fallback_section() -> None:
    xml = "<r><nota-van-toelichting>a<b>b</b></nota-van-toelichting></r>"
    assert _stb("stb-2015-1", xml).props["text"] == "a b"
    assert (
        _stb("stb-2015-1", "<r><toelichting>x</toelichting></r>").props["text"] == "x"
    )
    xml = "<r><nota_van_toelichting/><toelichting>y</toelichting></r>"
    assert _stb("stb-2015-1", xml).props["text"] == "y"
    assert _stb("stb-2015-1", "<r/>").props["text"] == ""


def test_bwb_id_extraction_uppercases_first_hit() -> None:
    several = "<r>see bwbr0001234 and BWBR0005678 and BWBV0001000</r>"
    assert _stb("stb-2015-1", several).props["bwb_id"] == "BWBR0001234"
    assert "bwb_id" not in _stb("stb-2015-1", "<r>none</r>").props
    assert _stb("stb-2015-1", '<r a="BWBV0001000"/>').props["bwb_id"] == "BWBV0001000"
    assert _stb("stb-2015-1", "<r>bwbr0001234</r>").props["bwb_id"] == "BWBR0001234"
    assert _stcrt("stcrt-2020-5", "<r>bwbr0001234</r>").props["bwb_id"] == "BWBR0001234"
    assert "bwb_id" not in _stcrt("stcrt-2020-5", "<r/>").props


def test_stcrt_parsing() -> None:
    props = _stcrt(
        "stcrt-2020-55",
        "<r><titel>T</titel><tekst>Hello<b>x</b>world</tekst>"
        "<publicatiedatum>2020-03-04T10:00:00</publicatiedatum></r>",
    ).props
    assert props["title"] == "T"
    assert props["text"] == "Helloxworld"  # find_text joins itertext without separator
    assert props["year"] == "2020" and props["number"] == "55"
    assert props["date"] == "2020-03-04"
    assert props["display_name"] == "Stcrt. 2020/55: T"


def test_stcrt_text_fallback_and_missing_identifier() -> None:
    props = _stcrt("weird", "<r><a>x</a><b>y</b></r>").props
    assert props["text"] == "x y"  # itertext joined with a space
    assert (props["year"], props["number"]) == ("", "")
    assert props["title"] == "Staatscourant /"


def test_stcrt_date_is_validated() -> None:
    def date(text: str) -> Any:
        return _stcrt("stcrt-2020-5", f"<r><datum>{text}</datum></r>").props.get("date")

    assert date("2020-03-04") == "2020-03-04"
    assert date("2020-03-04T10:00:00") == "2020-03-04"
    # ``iso_date`` only accepts a real YYYY-MM-DD, so anything else sets no date.
    assert date("05-03-2020 om 10:00") is None
    assert date("garbage-text-here") is None
