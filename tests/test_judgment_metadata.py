"""What ``core/judgment_metadata.py`` reads of the XML of a judgment: its text, its RDF
metadata, its court and its relations."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest

from lawgraph.core import judgment_metadata

NS = "http://example.org/ns"


def _el(xml: str) -> ET.Element:
    return ET.fromstring(xml)


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
    extract = judgment_metadata.extract_judgment_text
    summary, text = extract(judgment_metadata.parse_judgment(_JUDGMENT_XML))
    assert summary == "Samenvatting  tekst"
    assert text is not None and text.startswith("Info kop")
    assert "Procesverloop" in text and "Losse alinea." in text


def test_rechtspraak_extract_judgment_text_empty_elements() -> None:
    extract = judgment_metadata.extract_judgment_text
    parse = judgment_metadata.parse_judgment
    assert extract(parse("<r><inhoudsindicatie/><uitspraak/></r>")) == (None, None)
    # the first inhoudsindicatie decides, even when empty
    xml2 = "<r><inhoudsindicatie/><inhoudsindicatie>x</inhoudsindicatie></r>"
    assert extract(parse(xml2)) == (None, None)


def test_rechtspraak_extract_judgment_text_joins_multiple_uitspraak_blocks() -> None:
    extract = judgment_metadata.extract_judgment_text
    xml = "<r><uitspraak>a</uitspraak><uitspraak> </uitspraak><uitspraak>b</uitspraak></r>"
    assert extract(judgment_metadata.parse_judgment(xml)) == (None, "a\n\nb")


def test_rechtspraak_extract_rdf_metadata() -> None:
    extract = judgment_metadata.extract_rdf_metadata
    meta, subjects = extract(judgment_metadata.parse_judgment(_JUDGMENT_XML))
    assert meta["court"] == "Hoge Raad"
    assert meta["date"] == "2020-01-05"
    assert meta["case_number"] == "19/00001"
    assert meta["type"] == "Cassatie"
    assert meta["related_eclis"] == ["ECLI:NL:HR:2019:1", "ECLI:NL:GHAMS:2019:2"]
    assert subjects == ["Strafrecht", "Civiel recht"]


@pytest.mark.parametrize(
    "ecli,expected",
    [
        (None, (None, None, None)),
        ("", (None, None, None)),
        ("ECLI:NL:HR:2020:1", ("HR", "hoge_raad", "hoge_raad")),
        ("ecli:nl:hr:2020:1", ("HR", "hoge_raad", "hoge_raad")),
        ("ECLI:NL:GHAMS:2020:1", ("GHAMS", "gerechtshof", "gerechtshof")),
        ("ECLI:NL:RBAMS:2020:1", ("RBAMS", "rechtbank", "rechtbank")),
        (
            "ECLI:NL:CRVB:2020:1",
            ("CRVB", "centrale_raad_van_beroep", "centrale_raad_van_beroep"),
        ),
        ("ECLI:NL:RVS:2020:1", ("RVS", "raad_van_state", "raad_van_state")),
        ("ECLI:NL:TGZRAMS:2020:1", ("TGZRAMS", "tuchtcollege", "tuchtcollege")),
        (
            "ECLI:NL:OGHACMB:2020:1",
            ("OGHACMB", "koninkrijksinstantie", "gemeenschappelijk_hof_van_justitie"),
        ),
        ("ECLI:NL:AGAMS:1990:1", ("AGAMS", "andere_instantie", "ambtenarengerecht")),
        ("ECLI:NL:PHR:2019:496", ("PHR", "parket", "parket")),
        ("ECLI:CE:ECHR:2020:1", ("ECHR", "ehrm", "ehrm")),
        ("ECLI:NL:ZZZ:2020:1", ("ZZZ", None, None)),
        ("ECLI:NL", (None, None, None)),
        ("garbage", (None, None, None)),
    ],
)
def test_derive_court(ecli: str | None, expected: tuple[Any, Any, Any]) -> None:
    assert judgment_metadata.derive_court(ecli) == expected


def test_compose_display_name() -> None:
    compose = judgment_metadata.compose_display_name
    assert compose({"court": "HR", "date_eff": "d", "case_number": "n"}) == "HR d / n"
    assert compose({"court": "HR", "date_eff": "d"}) == "HR d"
    assert compose({"ecli": "E"}) == "E"
    assert compose({}) is None


def test_relation_ecli_extraction() -> None:
    fn = judgment_metadata.relation_ecli
    assert fn(_el("<r> ecli:nl:hr:1 </r>")) == "ECLI:NL:HR:1"
    assert fn(_el("<r/>")) is None
    assert fn(_el("<r>other</r>")) is None
    res = _el(f'<r xmlns:rdf="{NS}" rdf:resource="http://h?id=ECLI:NL:X:1"/>')
    assert fn(res) == "ECLI:NL:X:1"
    assert fn(_el('<r resource="http://h/no-id"/>')) is None


@pytest.mark.parametrize("payload", [None, "", "<bad", "geen xml"])
def test_a_judgment_that_is_no_xml_raises_instead_of_reading_as_empty(payload) -> None:
    """Three extractors each swallowed the parse error: the judgment became a node with
    no court, no date and no text, and nothing said so."""
    with pytest.raises(ValueError, match="not XML"):
        judgment_metadata.parse_judgment(payload)


# The relations as the open data of the Rechtspraak writes them (ECLI:NL:HR:2026:1350): the
# ECLI is an attribute, the text says what it is.
_RELATIONS_XML = """<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:dcterms="http://purl.org/dc/terms/" xmlns:ecli="https://e-justice.europa.eu/ecli"
    xmlns:psi="http://psi.rechtspraak.nl/" xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <rdf:Description>
    <dcterms:relation rdfs:label="Formele relatie" ecli:resourceIdentifier="ECLI:NL:PHR:2026:594"
      psi:type="http://psi.rechtspraak.nl/conclusie"
      psi:aanleg="http://psi.rechtspraak.nl/eerdereAanleg">
      Conclusie: ECLI:NL:PHR:2026:594</dcterms:relation>
    <dcterms:relation rdfs:label="Formele relatie" ecli:resourceIdentifier="ECLI:NL:GHAMS:2024:3036"
      psi:type="http://psi.rechtspraak.nl/cassatie"
      psi:aanleg="http://psi.rechtspraak.nl/eerdereAanleg">
      In cassatie op : ECLI:NL:GHAMS:2024:3036</dcterms:relation>
    <dcterms:relation rdfs:label="Formele relatie" ecli:resourceIdentifier="ECLI:NL:HR:2027:1"
      psi:type="http://psi.rechtspraak.nl/verwijzing"
      psi:aanleg="http://psi.rechtspraak.nl/latereAanleg">
      Na verwijzing: ECLI:NL:HR:2027:1</dcterms:relation>
  </rdf:Description>
</rdf:RDF>"""


def test_the_earlier_instance_is_read_from_the_attribute_and_nothing_else_is() -> None:
    """The judgment that was appealed, not the conclusion of the A-G on it, nor the one after."""
    meta, _ = judgment_metadata.extract_rdf_metadata(
        judgment_metadata.parse_judgment(_RELATIONS_XML)
    )
    assert meta["related_eclis"] == ["ECLI:NL:GHAMS:2024:3036"]


def test_rechtspraak_extract_law_references() -> None:
    ids = [
        "jci1.31:c:BWBR0001854",
        "jci1.31:c:BWBR0001854&amp;artikel=98&amp;g=2015-06-12",
        "jci1.31:c:BWBR0003045&amp;artikel=349a, 355 (oud)",
        "jci1.31:c:BWBR0001854&amp;artikel=98",
        "niet-een-jci",
    ]
    refs = "".join(f'<dcterms:references bwb:resourceIdentifier="{i}"/>' for i in ids)
    xml = (
        '<open xmlns:dcterms="http://purl.org/dc/terms/" xmlns:bwb="http://x/bwb">'
        f"{refs}<dcterms:references/></open>"
    )
    found = judgment_metadata.extract_law_references(ET.fromstring(xml))
    assert found == [
        {"bwb_id": "BWBR0001854", "article": None, "date": None, "old": False},
        {"bwb_id": "BWBR0001854", "article": "98", "date": "2015-06-12", "old": False},
        {"bwb_id": "BWBR0003045", "article": "349a", "date": None, "old": False},
        {"bwb_id": "BWBR0003045", "article": "355", "date": None, "old": True},
    ]
    assert judgment_metadata.extract_law_references(ET.fromstring("<r/>")) == []
