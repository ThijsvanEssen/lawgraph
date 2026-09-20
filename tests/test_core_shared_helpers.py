"""Tests for the pure helpers consolidated into ``lawgraph.core``.

These assertions were written against the former per-module copies (see the
characterization commit) and pin their behaviour, including empty/None inputs
and whitespace handling. Where the copies differed, the shared function takes an
explicit parameter (``sep``, ``skip_empty``, ``collapse``, ``skip_blank``) or a
separate function (``find_own_text``).
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from lawgraph.clients import _sru
from lawgraph.core import annex_xml, judgments
from lawgraph.core import xml as core_xml
from lawgraph.core.identifiers import STB_ID_PATTERN, STCRT_ID_PATTERN, clean_ids
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.core.time import odata_datetime, sortable_date
from lawgraph.core.values import first_str, first_text_prop, next_page_link
from lawgraph.pipelines.normalize.base import NormalizePipelineBase
from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
from lawgraph.pipelines.normalize.staatscourant import StaatscourantNormalizePipeline

NS = "http://example.org/ns"


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


# ── local_name ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "tag,expected",
    [
        ("plain", "plain"),
        (f"{{{NS}}}tag", "tag"),
        ("", ""),
        (f"{{{NS}}}", ""),
    ],
)
def test_local_name(tag: str, expected: str) -> None:
    assert core_xml.local_name(tag) == expected


# ── find_text / _first_text / _sru._find_text ───────────────────────────────


def test_find_text_skips_empty_matches_and_joins_itertext_without_separator() -> None:
    root = _el("<r><t> </t><t>a<b>b</b> c</t></r>")
    assert core_xml.find_text(root, "t") == "ab c"


def test_find_text_returns_none_when_missing_or_all_empty() -> None:
    assert core_xml.find_text(_el("<r><t/></r>"), "t") is None
    assert core_xml.find_text(_el("<r/>"), "t") is None


def test_find_text_matches_namespaced_and_any_of_several_names() -> None:
    root = _el(f'<r xmlns:n="{NS}"><n:two>2</n:two><one>1</one></r>')
    assert core_xml.find_text(root, "one", "two") == "2"  # document order wins


def test_find_text_includes_the_element_itself() -> None:
    assert core_xml.find_text(_el("<t>self</t>"), "t") == "self"


def test_annex_first_text_returns_first_match_even_if_empty_and_collapses() -> None:
    def first(root: ET.Element) -> str | None:
        return core_xml.find_text(root, "nr", collapse=True, skip_empty=False)

    assert first(_el("<r><nr>  a \n  b<x> c</x> </nr></r>")) == "a b c"
    # first match wins even when it is empty (skip_empty=True would try the next)
    assert first(_el("<r><nr/><nr>2</nr></r>")) is None
    assert first(_el("<r/>")) is None
    root = _el("<r><nr/><nr>2</nr></r>")
    assert core_xml.find_text(root, "nr", collapse=True) == "2"


def test_sru_find_text_uses_own_text_only_and_first_match_wins() -> None:
    assert core_xml.find_own_text(_el("<r><a> x </a></r>"), "a") == "x"
    assert core_xml.find_own_text(_el("<r><a>x<b>y</b></a></r>"), "a") == "x"
    assert core_xml.find_own_text(_el("<r><a/><a>2</a></r>"), "a") is None
    assert core_xml.find_own_text(_el("<r><a>  </a></r>"), "a") is None
    assert core_xml.find_own_text(_el("<a>self</a>"), "a") == "self"
    assert (
        core_xml.find_own_text(_el(f'<r xmlns:n="{NS}"><n:a>ns</n:a></r>'), "a") == "ns"
    )


# ── extract_section_text ─────────────────────────────────────────────────────


def test_extract_section_text_joins_itertext_with_space() -> None:
    root = _el("<r><s>a<b>b</b>c</s></r>")
    assert core_xml.extract_section_text(root, "s") == "a b c"


def test_extract_section_text_first_match_wins_even_if_empty() -> None:
    assert core_xml.extract_section_text(_el("<r><s/><s>x</s></r>"), "s") is None
    assert core_xml.extract_section_text(_el("<r><s>  </s></r>"), "s") is None
    assert core_xml.extract_section_text(_el("<r/>"), "s") is None


def test_extract_section_text_any_name_and_self() -> None:
    assert (
        core_xml.extract_section_text(_el("<r><b>1</b><a>2</a></r>"), "a", "b") == "1"
    )
    assert core_xml.extract_section_text(_el("<s>me</s>"), "s") == "me"


# ── rechtspraak _xml_clean and section extraction ────────────────────────────


def test_rechtspraak_xml_clean_joins_with_space_and_strips() -> None:
    assert core_xml.text_of(_el("<p> a<b>b</b>c </p>"), " ") == "a b c"
    assert core_xml.text_of(_el("<p/>"), " ") == ""


_JUDGMENT_XML = f"""<open xmlns:dc="http://purl.org/dc/elements/1.1/"
      xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:psi="http://psi.rechtspraak.nl/"
      xmlns="{NS}">
  <rdf:RDF>
    <rdf:Description>
      <dc:creator>Hoge Raad</dc:creator>
      <dc:creator>Ignored</dc:creator>
      <dc:date>2020-01-05</dc:date>
      <psi:zaaknummer>19/00001</psi:zaaknummer>
      <psi:procedure>Cassatie</psi:procedure>
      <dc:subject>Strafrecht</dc:subject>
      <dc:subject>  </dc:subject>
      <dc:subject>Civiel recht</dc:subject>
      <dc:relation>ecli:nl:hr:2019:1</dc:relation>
      <dc:relation rdf:resource="http://x/y?id=ECLI:NL:GHAMS:2019:2"/>
      <dc:relation>not-an-ecli</dc:relation>
      <dc:relation/>
    </rdf:Description>
  </rdf:RDF>
  <inhoudsindicatie><para>Samenvatting</para> tekst</inhoudsindicatie>
  <uitspraak>
    <uitspraak.info>Info kop</uitspraak.info>
    <section nr="1">
      <title>Procesverloop</title>
      <para>Eerste alinea.</para>
      <al>Tweede<emphasis>alinea</emphasis>.</al>
      <footnote>voetnoot</footnote>
      <section nr="1.1"><title>Sub</title><para>Diep.</para></section>
      <uitspraak.info>Inline info</uitspraak.info>
      <other>Overig</other>
      <nr>1</nr>
    </section>
    <section><para>Zonder titel</para></section>
    <para>Losse alinea.</para>
    <ignored>x</ignored>
  </uitspraak>
</open>"""


def test_rechtspraak_extract_judgment_text() -> None:
    extract = judgments.extract_judgment_text
    summary, text = extract(_JUDGMENT_XML)
    assert summary == "Samenvatting  tekst"
    assert text is not None and text.startswith("Info kop")
    assert "Procesverloop" in text and "Losse alinea." in text
    assert extract(None) == (None, None)
    assert extract("") == (None, None)
    assert extract("<bad") == (None, None)


def test_rechtspraak_extract_judgment_text_empty_elements() -> None:
    extract = judgments.extract_judgment_text
    assert extract("<r><inhoudsindicatie/><uitspraak/></r>") == (None, None)
    # the first inhoudsindicatie decides, even when empty
    xml2 = "<r><inhoudsindicatie/><inhoudsindicatie>x</inhoudsindicatie></r>"
    assert extract(xml2) == (None, None)


def test_rechtspraak_extract_judgment_text_joins_multiple_uitspraak_blocks() -> None:
    extract = judgments.extract_judgment_text
    xml = "<r><uitspraak>a</uitspraak><uitspraak> </uitspraak><uitspraak>b</uitspraak></r>"
    assert extract(xml) == (None, "a\n\nb")


def test_rechtspraak_extract_rdf_metadata() -> None:
    extract = judgments.extract_rdf_metadata
    meta, subjects = extract(_JUDGMENT_XML)
    assert meta["court"] == "Hoge Raad"
    assert meta["date"] == "2020-01-05"
    assert meta["case_number"] == "19/00001"
    assert meta["type"] == "Cassatie"
    assert meta["related_eclis"] == ["ECLI:NL:HR:2019:1", "ECLI:NL:GHAMS:2019:2"]
    assert subjects == ["Strafrecht", "Civiel recht"]
    assert extract(None) == ({}, [])
    assert extract("<bad") == ({}, [])


def test_rechtspraak_extract_sections() -> None:
    extract = judgments.extract_sections
    assert extract(_JUDGMENT_XML) == [
        {"number": None, "kind": "subheading", "text": "Info kop"},
        {"number": "1", "kind": "heading", "text": "Procesverloop"},
        {"number": None, "kind": "body", "text": "Eerste alinea."},
        {"number": None, "kind": "body", "text": "Tweede alinea ."},
        {"number": "1.1", "kind": "subheading", "text": "Sub"},
        {"number": None, "kind": "body", "text": "Diep."},
        {"number": None, "kind": "subheading", "text": "Inline info"},
        {"number": None, "kind": "body", "text": "Overig"},
        {"number": None, "kind": "body", "text": "Zonder titel"},
        {"number": None, "kind": "body", "text": "Losse alinea."},
    ]
    assert extract(None) == []
    assert extract("<bad") == []
    assert extract("<r/>") == []


def test_rechtspraak_section_title_falls_back_to_section_text() -> None:
    paragraphs: list[dict[str, Any]] = []
    section = _el('<section nr=" 7 ">  kop <para>x</para></section>')
    judgments._process_section(section, paragraphs)
    assert paragraphs[0] == {"number": "7", "kind": "heading", "text": "kop"}


@pytest.mark.parametrize(
    "ecli,expected",
    [
        (None, (None, None)),
        ("", (None, None)),
        ("ECLI:NL:HR:2020:1", ("HR", "hoge_raad")),
        ("ecli:nl:hr:2020:1", ("HR", "hoge_raad")),
        ("ECLI:NL:GHAMS:2020:1", ("GHAMS", "gerechtshof")),
        ("ECLI:NL:RBAMS:2020:1", ("RBAMS", "rechtbank")),
        ("ECLI:NL:CRVB:2020:1", ("CRVB", "bijzonder")),
        ("ECLI:NL", (None, None)),
        ("garbage", (None, None)),
    ],
)
def test_derive_court_tier(ecli: str | None, expected: tuple[Any, Any]) -> None:
    assert judgments.derive_court_tier(ecli) == expected


def test_compose_display_name() -> None:
    compose = judgments.compose_display_name
    assert compose({"court": "HR", "date_eff": "d", "case_number": "n"}) == "HR d / n"
    assert compose({"court": "HR", "date_eff": "d"}) == "HR d"
    assert compose({"ecli": "E"}) == "E"
    assert compose({}) is None


def test_relation_ecli_extraction() -> None:
    fn = judgments.relation_ecli
    assert fn(_el("<r> ecli:nl:hr:1 </r>")) == "ECLI:NL:HR:1"
    assert fn(_el("<r/>")) is None
    assert fn(_el("<r>other</r>")) is None
    res = _el(f'<r xmlns:rdf="{NS}" rdf:resource="http://h?id=ECLI:NL:X:1"/>')
    assert fn(res) == "ECLI:NL:X:1"
    assert fn(_el('<r resource="http://h/no-id"/>')) is None


# ── bijlage extraction ───────────────────────────────────────────────────────


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
        {"index": 0, "name": "Energie"},
        {"index": 1, "name": "Water en gas"},
    ]
    assert annex_xml.extract_description(root) == "Intro tekst.\nTwee."
    assert annex_xml.extract_description(_el("<bijlage/>")) is None


def test_annex_entry_and_description_caps() -> None:
    lis = "".join(f"<li>e{i}</li>" for i in range(250))
    assert len(annex_xml.extract_entries(_el(f"<b>{lis}</b>"))) == 200
    long_al = "x" * 1500
    xml = f"<b><al>{long_al}</al><al>{long_al}</al><al>{long_al}</al></b>"
    desc = annex_xml.extract_description(_el(xml))
    assert desc is not None
    assert len(desc) == 2000  # two paragraphs (>=2000 chars) then truncated


# ── raw-record accessors ─────────────────────────────────────────────────────


def test_raw_record_accessors() -> None:
    assert payload_text({"payload_text": "x"}) == "x"
    assert payload_text({"payload_text": 1}) is None
    assert payload_text({}) is None
    assert payload_json({"payload_json": {"a": 1}}) == {"a": 1}
    assert payload_json({"payload_json": []}) == {}
    assert meta({"meta": {"a": 1}}) == {"a": 1}
    assert meta({"meta": None}) == {}


def test_normalize_base_delegates_to_raw_records() -> None:
    assert NormalizePipelineBase._payload_text is payload_text
    assert NormalizePipelineBase._payload_json is payload_json
    assert NormalizePipelineBase._meta is meta


# ── ID patterns ──────────────────────────────────────────────────────────────


def test_publication_id_patterns() -> None:
    assert STB_ID_PATTERN.search("x STB-2015-134 y").groups() == ("2015", "134")  # type: ignore[union-attr]
    assert STCRT_ID_PATTERN.search("STCRT-2020-55").groups() == ("2020", "55")  # type: ignore[union-attr]
    assert STCRT_ID_PATTERN.search("stb-2020-55") is None
    assert STB_ID_PATTERN.search("stcrt-2020-55") is None


# ── staatsblad / staatscourant parsing ───────────────────────────────────────


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


# ── staatsblad client: ref from BWB xml ──────────────────────────────────────


def test_extract_staatsblad_ref_from_bwb_xml() -> None:
    fn = staatsblad_ref_from_bwb_xml
    xml = "<r><publicatiejaar>2015</publicatiejaar><publicatienummer> 134 </publicatienummer></r>"
    assert fn(xml) == ("2015", "134")
    bad_year = "<r><publicatiejaar>abc</publicatiejaar><publicatienummer>1</publicatienummer></r>"
    assert fn(bad_year) is None
    assert fn('<r><x a="stb-2001-55"/></r>') == ("2001", "55")
    assert fn("<r>tekst stb-2001-56</r>") == ("2001", "56")
    assert fn("<r/>") is None
    assert fn("<bad") is None


# ── retrieve id cleaning ─────────────────────────────────────────────────────


def test_clean_ids() -> None:
    norm = clean_ids
    assert norm(None) == []
    assert norm([]) == []
    assert norm([" A ", "", None, "B", "A", "  "]) == ["A", "B"]  # type: ignore[list-item]


# ── clients: pure statics ────────────────────────────────────────────────────


def test_format_odata_datetime() -> None:
    fmt = odata_datetime
    assert fmt(dt.datetime(2024, 1, 2, 3, 4, 5, 999)) == "2024-01-02T03:04:05Z"
    aware = dt.datetime(2024, 1, 2, 5, 4, 5, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert fmt(aware) == "2024-01-02T03:04:05Z"


def test_bwb_date_for_sort() -> None:
    fn = sortable_date
    assert fn(None) == dt.date.min
    assert fn("") == dt.date.min
    assert fn("garbage") == dt.date.min
    assert fn("2020-02-03") == dt.date(2020, 2, 3)
    assert fn("9999-12-31") == dt.date(9999, 12, 31)


def test_extract_next_link() -> None:
    fn = next_page_link
    assert fn({"n": " http://x "}, "n") == "http://x"
    assert fn({"n": "  "}, "n") is None
    assert fn({"n": 5}, "n") is None
    assert fn({"n": "x"}, None) is None
    assert fn([], "n") is None
    assert fn({}, "n") is None


def test_first_non_none_str_and_first_non_empty() -> None:
    assert first_str([None, "", "x"]) == ""  # empty string counts
    assert first_str([None, 5]) == "5"
    assert first_str([None, None]) is None
    assert first_str([]) is None
    assert first_str([None, " x "]) == " x "  # not stripped
    assert first_str([None, "  ", " x "], skip_blank=True) == "x"
    assert first_str([None, 5], skip_blank=True) == "5"
    assert first_str([None, ""], skip_blank=True) is None


def test_first_text_prop() -> None:
    assert first_text_prop({"a": " ", "b": 3, "c": " x "}, "a", "b", "c") == " x "
    assert first_text_prop({}, "a") is None


# ── SRU record parsing ───────────────────────────────────────────────────────


def test_parse_sru_records() -> None:
    xml = f"""<searchRetrieveResponse xmlns="{NS}"><records>
      <record><recordData><identifier>stb-2015-134</identifier>
        <title> Titel </title><url>http://u</url><date>2015-01-01</date>
      </recordData></record>
      <record><recordData><recordIdentifier>stb-2016-9</recordIdentifier></recordData></record>
      <record><recordData><identifier>other</identifier></recordData></record>
      <record><recordData/></record>
    </records></searchRetrieveResponse>"""
    recs = _sru.parse_sru_records(
        _el(xml),
        id_pattern=re.compile(r"stb-(\d{4})-(\d+)"),
        extra_fields=("date",),
        default_title_prefix="Staatsblad",
    )
    assert recs == [
        {
            "identifier": "stb-2015-134",
            "year": "2015",
            "number": "134",
            "title": "Titel",
            "content_url": "http://u",
            "date": "2015-01-01",
        },
        {
            "identifier": "stb-2016-9",
            "year": "2016",
            "number": "9",
            "title": "Staatsblad 2016/9",
            "content_url": None,
            "date": None,
        },
    ]
