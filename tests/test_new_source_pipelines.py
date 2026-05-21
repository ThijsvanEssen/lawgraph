"""Smoke tests for the five new source normalize pipelines.

Each test drives the parse/normalize logic directly without a real database by
supplying a minimal FakeStore and representative raw_sources records.
"""

from __future__ import annotations

from typing import Any

from lawgraph.models import Node, NodeType

# ---------------------------------------------------------------------------
# Shared FakeStore — just enough surface to support normalize_nodes()
# ---------------------------------------------------------------------------


class FakeStore:
    def __init__(self) -> None:
        self.upserted: list[Node] = []

    def query(self, aql: str, bind_vars: dict | None = None) -> list[Any]:
        return []

    def insert_or_update(self, node: Node) -> Node:
        self.upserted.append(node)
        return node

    def get_node(self, collection: str, key: str) -> Node | None:
        return None


def _raw(
    external_id: str, payload_text: str | None = None, payload_json: Any = None
) -> dict:
    rec: dict[str, Any] = {"external_id": external_id}
    if payload_text is not None:
        rec["payload_text"] = payload_text
    if payload_json is not None:
        rec["payload_json"] = payload_json
    return rec


# ---------------------------------------------------------------------------
# Staatsblad
# ---------------------------------------------------------------------------

_STB_XML = """<?xml version="1.0"?>
<root>
  <citeertitel>Besluit risico's zware ongevallen 2015</citeertitel>
  <publicatiejaar>2015</publicatiejaar>
  <publicatienummer>134</publicatienummer>
  <nota-van-toelichting>
    <al>Op grond van BWBR0001234 wordt het volgende besloten.</al>
  </nota-van-toelichting>
</root>"""


def test_staatsblad_normalize_creates_publication():
    from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline

    store = FakeStore()
    pipeline = StaatsbladNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("stb-2015-134", payload_text=_STB_XML)])

    assert len(nodes) == 1
    node = next(iter(nodes.values()))
    assert node.type == NodeType.PUBLICATION
    assert node.props["year"] == "2015"
    assert node.props["number"] == "134"
    assert node.props["bwb_id"] == "BWBR0001234"


def test_staatsblad_normalize_skips_empty_payload():
    from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline

    store = FakeStore()
    pipeline = StaatsbladNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("stb-2020-1", payload_text="")])
    assert len(nodes) == 0


# ---------------------------------------------------------------------------
# Staatscourant
# ---------------------------------------------------------------------------

_STCRT_XML = """<?xml version="1.0"?>
<root>
  <citeertitel>Regeling tegemoetkoming 2020</citeertitel>
  <publicatiejaar>2020</publicatiejaar>
  <publicatienummer>55</publicatienummer>
  <officiele-titel>Regeling tegemoetkoming 2020</officiele-titel>
  <tekst>Op grond van BWBR0005821 wordt vastgesteld.</tekst>
</root>"""


def test_staatscourant_normalize_creates_publication():
    from lawgraph.pipelines.normalize.staatscourant import (
        StaatscourantNormalizePipeline,
    )

    store = FakeStore()
    pipeline = StaatscourantNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("stcrt-2020-55", payload_text=_STCRT_XML)])

    assert len(nodes) == 1
    node = next(iter(nodes.values()))
    assert node.type == NodeType.PUBLICATION
    assert node.props["year"] == "2020"
    assert node.props["bwb_id"] == "BWBR0005821"


def test_staatscourant_normalize_skips_empty_payload():
    from lawgraph.pipelines.normalize.staatscourant import (
        StaatscourantNormalizePipeline,
    )

    store = FakeStore()
    pipeline = StaatscourantNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("stcrt-2020-55", payload_text="")])
    assert len(nodes) == 0


# ---------------------------------------------------------------------------
# ECHR
# ---------------------------------------------------------------------------

_ECHR_PAYLOAD = {
    "itemid": "001-12345",
    "appno": "12345/67",
    "docname": "CASE OF TEST v. NETHERLANDS",
    "kpdate": "2022-03-15",
    "respondent": "Netherlands",
    "importance": 1,
    "article": ["6", "8"],
    "conclusion": "Violation of Article 6",
    "originatingbody": "Grand Chamber",
}


def test_echr_normalize_creates_judgment():
    from lawgraph.pipelines.normalize.echr import EchrNormalizePipeline

    store = FakeStore()
    pipeline = EchrNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("001-12345", payload_json=_ECHR_PAYLOAD)])

    assert len(nodes) == 1
    node = next(iter(nodes.values()))
    assert node.type == NodeType.JUDGMENT
    assert node.props["appno"] == "12345/67"
    assert node.props["respondent"] == "Netherlands"
    assert node.props["articles"] == ["6", "8"]


def test_echr_normalize_skips_empty_payload():
    from lawgraph.pipelines.normalize.echr import EchrNormalizePipeline

    store = FakeStore()
    pipeline = EchrNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("x", payload_json=None)])
    assert len(nodes) == 0


# ---------------------------------------------------------------------------
# Verdragenbank
# ---------------------------------------------------------------------------

_VERDRAG_PAYLOAD = {
    "uri": "https://verdragenbank.overheid.nl/nt/12345",
    "verdragsnummer": "12345",
    "title_nl": "Verdrag inzake testonderwerp",
    "title_en": "Treaty on test subject",
    "treaty_type": "bilateral",
    "status": "in force",
    "date_signed": "1990-06-01",
    "date_in_force": "1991-01-01",
    "parties": ["Netherlands", "Germany"],
}


def test_verdragenbank_normalize_creates_instrument():
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    store = FakeStore()
    pipeline = VerdragenbankNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("12345", payload_json=_VERDRAG_PAYLOAD)])

    assert len(nodes) == 1
    node = next(iter(nodes.values()))
    assert node.type == NodeType.INSTRUMENT
    assert node.props["kind"] == "bilateraalverdrag"
    assert node.props["status"] == "in force"
    assert node.props["date_signed"] == "1990-06-01"


def test_verdragenbank_normalize_multilateral():
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    payload = {
        **_VERDRAG_PAYLOAD,
        "treaty_type": "multilateral",
        "uri": "https://vb/99",
    }
    store = FakeStore()
    pipeline = VerdragenbankNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("99", payload_json=payload)])

    node = next(iter(nodes.values()))
    assert node.props["kind"] == "multilateraalverdrag"


# ---------------------------------------------------------------------------
# Eerste Kamer
# ---------------------------------------------------------------------------

_EK_PAYLOAD = {
    "Id": "ek-stuk-abc123",
    "Nummer": "36000",
    "DossierNummer": "36000",
    "Ondernummer": "A",
    "Soort": "Eindverslag",
    "Datum": "2023-05-10",
    "Titel": "Eindverslag commissie Justitie",
    "Onderwerp": "Wetsvoorstel testonderwerp",
    "Vergaderjaar": "2022-2023",
    "Bijgewerkt": "2023-05-11T00:00:00",
}


def test_eerstekamer_normalize_creates_publication():
    from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline

    store = FakeStore()
    pipeline = EerstekamerNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("ek-stuk-abc123", payload_json=_EK_PAYLOAD)])

    assert len(nodes) == 1
    node = next(iter(nodes.values()))
    assert node.type == NodeType.PUBLICATION
    assert node.props["soort"] == "Eindverslag"
    assert node.props["dossier_nummer"] == "36000"


def test_eerstekamer_normalize_skips_missing_id():
    from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline

    store = FakeStore()
    pipeline = EerstekamerNormalizePipeline(store=store)
    nodes = pipeline.normalize_nodes([_raw("", payload_json={})])
    assert len(nodes) == 0
