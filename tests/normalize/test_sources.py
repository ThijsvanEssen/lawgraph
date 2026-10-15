"""Normalize pipelines of the smaller sources.

Staatsblad, Staatscourant, ECHR and Verdragenbank. Each test
drives the parse/normalize logic directly without a real database by supplying
an ``InMemoryStore`` and representative raw_sources records.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db.queries import raw as raw_queries
from tests.fakes import InMemoryStore
from tests.paths import fixture_text


def _written(store: InMemoryStore) -> Node:
    """The one node the pipeline wrote."""
    [(collection, docs)] = store.nodes.items()
    [doc] = docs.values()
    return Node.from_document(collection, doc)


def _count(store: InMemoryStore) -> int:
    """How many nodes the pipeline wrote."""
    return sum(len(docs) for docs in store.nodes.values())


def _raw(
    external_id: str,
    payload_text: str | None = None,
    payload_json: Any = None,
    meta: dict[str, Any] | None = None,
) -> dict:
    rec: dict[str, Any] = {"external_id": external_id}
    if meta is not None:
        rec["meta"] = meta
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

    store = InMemoryStore()
    pipeline = StaatsbladNormalizePipeline(store=store)
    pipeline.write([_raw("stb-2015-134", payload_text=_STB_XML)], PipelineResult())

    assert _count(store) == 1
    node = _written(store)
    assert node.type == NodeType.DOCUMENT
    assert node.props["year"] == "2015"
    assert node.props["number"] == "134"
    assert node.props["bwb_id"] == "BWBR0001234"


def test_the_nota_van_toelichting_of_a_real_amvb_is_its_text():
    """stb-2025-263 as the repository serves it: the note is ``<nota-toelichting>``. Read
    as none, every Staatsblad note had an empty text and no EXPLAINS (web-1, 9,875)."""

    from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline

    xml = fixture_text("stb_2025_263.xml")
    store = InMemoryStore()
    StaatsbladNormalizePipeline(store=store).write(
        [_raw("stb-2025-263", payload_text=xml)], PipelineResult()
    )
    text = _written(store).props["text"]
    assert text.startswith("NOTA VAN TOELICHTING") and len(text) > 5000
    assert "Mediabesluit 2008" in text
    # its title is the publication's (``DC.title``), not the masthead "Staatsblad"
    assert _written(store).props["title"] == (
        "Besluit van 29 september 2025 tot wijziging van het Mediabesluit 2008 in "
        "verband met het stellen van nadere regels omtrent een investeringsverplichting "
        "voor Nederlands cultureel audiovisueel product"
    )


def test_staatsblad_normalize_keeps_the_regulation_retrieve_found_it_for():
    """The toestand of BWBR0009999 named this publication: that is the regulation it
    explains, not BWBR0001234, the first law its text cites."""
    from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline

    store = InMemoryStore()
    pipeline = StaatsbladNormalizePipeline(store=store)
    pipeline.write(
        [_raw("stb-2015-134", payload_text=_STB_XML, meta={"bwb_id": "BWBR0009999"})],
        PipelineResult(),
    )
    assert _written(store).props["bwb_id"] == "BWBR0009999"


def test_staatsblad_normalize_skips_empty_payload():
    from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline

    store = InMemoryStore()
    pipeline = StaatsbladNormalizePipeline(store=store)
    pipeline.write([_raw("stb-2020-1", payload_text="")], PipelineResult())
    assert _count(store) == 0


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

    store = InMemoryStore()
    pipeline = StaatscourantNormalizePipeline(store=store)
    pipeline.write([_raw("stcrt-2020-55", payload_text=_STCRT_XML)], PipelineResult())

    assert _count(store) == 1
    node = _written(store)
    assert node.type == NodeType.DOCUMENT
    assert node.props["year"] == "2020"
    assert node.props["bwb_id"] == "BWBR0005821"


def test_staatscourant_normalize_skips_empty_payload():
    from lawgraph.pipelines.normalize.staatscourant import (
        StaatscourantNormalizePipeline,
    )

    store = InMemoryStore()
    pipeline = StaatscourantNormalizePipeline(store=store)
    pipeline.write([_raw("stcrt-2020-55", payload_text="")], PipelineResult())
    assert _count(store) == 0


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
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline

    store = InMemoryStore()
    pipeline = ECHRNormalizePipeline(store=store)
    pipeline.write([_raw("001-12345", payload_json=_ECHR_PAYLOAD)], PipelineResult())

    assert _count(store) == 1
    node = _written(store)
    assert node.type == NodeType.JUDGMENT
    assert node.props["appno"] == "12345/67"
    assert node.props["respondent"] == "Netherlands"
    assert node.props["articles"] == ["6", "8"]


def test_echr_normalize_skips_empty_payload():
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline

    store = InMemoryStore()
    pipeline = ECHRNormalizePipeline(store=store)
    pipeline.write([_raw("x", payload_json=None)], PipelineResult())
    assert _count(store) == 0


def test_echr_names_why_a_record_gives_no_judgment():
    from lawgraph.config.constants import RAW_KIND_ECHR_TEXT
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline

    english = {**_ECHR_PAYLOAD, "ecli": "ECLI:CE:ECHR:2022:0315JUD001234567"}
    french = {**english, "itemid": "001-12346", "languageisocode": "FRE"}
    text = {"kind": RAW_KIND_ECHR_TEXT}
    store = InMemoryStore()
    pipeline = ECHRNormalizePipeline(store=store)
    progress = pipeline.progress
    result = PipelineResult()

    pipeline.write(
        [
            _raw("001-1", payload_json=None),
            _raw("", payload_json={"docname": "CASE OF NOBODY"}),
            _raw("001-12345", payload_json={**english, "languageisocode": "ENG"}),
            _raw("001-12346", payload_json=french),
            {**_raw("001-2", payload_text=""), **text},
            {**_raw("001-3", payload_text="<w:document"), **text},
        ],
        result,
    )
    pipeline.add_outcomes(result)

    assert _count(store) == 1
    assert progress.skips == {
        "no payload": 1,
        "no item id": 1,
        "a translation; a better language is kept": 1,
        "no text": 1,
    }
    assert progress.failures == {"text not readable": 1}
    assert result.skipped == 5
    (error,) = result.errors
    assert "001-3" in error


@pytest.mark.parametrize(
    ("importance", "kept"), [("2", 2), (1, 1), (None, None), ("", None), ("key", None)]
)
def test_echr_importance_is_a_number_or_left_out(importance: Any, kept: Any) -> None:
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline

    store = InMemoryStore()
    pipeline = ECHRNormalizePipeline(store=store)
    progress = pipeline.progress
    pipeline.write(
        [_raw("001-12345", payload_json={**_ECHR_PAYLOAD, "importance": importance})],
        PipelineResult(),
    )

    assert _written(store).props.get("importance") == kept
    assert progress.problems == (
        {"importance not a number": 1} if importance == "key" else {}
    )


# ---------------------------------------------------------------------------
# Verdragenbank
# ---------------------------------------------------------------------------

_VERDRAG_PAYLOAD = {
    "uri": "https://verdragenbank.overheid.nl/nt/12345",
    "verdragsnummer": "12345",
    "title_nl": "Verdrag inzake testonderwerp",
    "title_en": "Treaty on test subject",
    "treaty_type": "Bilateraal",
    "status": "Inwerkinggetreden",
    "date_signed": "1990-06-01",
    "date_in_force": "1991-01-01",
    "parties": ["Netherlands", "Germany"],
}


def test_verdragenbank_normalize_creates_instrument():
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    store = InMemoryStore()
    pipeline = VerdragenbankNormalizePipeline(store=store)
    pipeline.write([_raw("12345", payload_json=_VERDRAG_PAYLOAD)], PipelineResult())

    assert _count(store) == 1
    node = _written(store)
    assert node.type == NodeType.INSTRUMENT
    assert node.props["kind"] == "bilateraalverdrag"
    assert node.props["status"] == "Inwerkinggetreden"
    assert node.props["in_force"] is True
    assert node.props["date_signed"] == "1990-06-01"


def test_verdragenbank_normalize_multilateral():
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    payload = {
        **_VERDRAG_PAYLOAD,
        "treaty_type": "Multilateraal",
        "uri": "https://vb/99",
    }
    store = InMemoryStore()
    pipeline = VerdragenbankNormalizePipeline(store=store)
    pipeline.write([_raw("99", payload_json=payload)], PipelineResult())

    node = _written(store)
    assert node.props["kind"] == "multilateraalverdrag"


def test_verdragenbank_only_a_treaty_in_force_is_in_force():
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    def in_force(status: str) -> bool:
        payload = {**_VERDRAG_PAYLOAD, "status": status}
        store = InMemoryStore()
        VerdragenbankNormalizePipeline(store=store).write(
            [_raw("12345", payload_json=payload)], PipelineResult()
        )
        return _written(store).props["in_force"]

    assert in_force("Inwerkinggetreden") is True
    for status in ("Buitenwerkinggetreden", "Totstandgekomen", "Geratificeerd"):
        assert in_force(status) is False


def test_verdragenbank_names_why_a_record_gives_no_treaty():
    from lawgraph.config.constants import RAW_KIND_VERDRAG_XML
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    item = {"kind": RAW_KIND_VERDRAG_XML}
    store = InMemoryStore()
    pipeline = VerdragenbankNormalizePipeline(store=store)
    progress = pipeline.progress
    result = PipelineResult()

    pipeline.write(
        [
            _raw("1", payload_json=None),
            _raw("", payload_json={"title_nl": "Verdrag zonder nummer"}),
            {**_raw("2", payload_text=""), **item},
            {**_raw("3", payload_text="<verdrag"), **item},
            _raw("12345", payload_json=_VERDRAG_PAYLOAD),
        ],
        result,
    )
    pipeline.add_outcomes(result)

    assert _count(store) == 1
    assert progress.skips == {"no payload": 1, "no treaty id": 1, "no item XML": 1}
    assert progress.failures == {"item XML not read": 1}
    assert result.skipped == 4
    (error,) = result.errors
    assert "3" in error and "not XML" in error


# ---------------------------------------------------------------------------
# Memory: raw records are streamed and no node is kept after it is written
# ---------------------------------------------------------------------------


def test_one_node_per_record_pipelines_stream_and_keep_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline
    from lawgraph.pipelines.normalize.eerstekamer import EerstekamerNormalizePipeline
    from lawgraph.pipelines.normalize.staatsblad import StaatsbladNormalizePipeline
    from lawgraph.pipelines.normalize.staatscourant import (
        StaatscourantNormalizePipeline,
    )
    from lawgraph.pipelines.normalize.verdragenbank import (
        VerdragenbankNormalizePipeline,
    )

    batch_sizes: list[int | None] = []

    def count_raw_records(store: Any, source: str, kinds: list[str]) -> int:
        batch_sizes.append(None)
        return 0

    def iter_raw_records(
        store: Any, *, batch_size: int, **_: Any
    ) -> Iterator[dict[str, Any]]:
        batch_sizes.append(batch_size)
        return iter([])

    monkeypatch.setattr(raw_queries, "count_raw_records", count_raw_records)
    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)

    for cls, large_payloads in (
        (StaatsbladNormalizePipeline, True),
        (StaatscourantNormalizePipeline, True),
        (ECHRNormalizePipeline, True),
        (EerstekamerNormalizePipeline, False),
        (VerdragenbankNormalizePipeline, False),
    ):
        batch_sizes.clear()
        pipeline = cls(store=InMemoryStore())
        raw = pipeline.fetch_raw()
        assert not isinstance(raw, list), cls.__name__
        with pytest.raises(StopIteration):
            next(iter(raw))
        # XML of up to 20 MB comes 20 at a time, small JSON records 1000 at a time.
        # first the count for the progress line, then the records
        assert batch_sizes == [None, 20 if large_payloads else 1000], cls.__name__
        pipeline.write(iter([]), PipelineResult())
        assert pipeline.store.writes.created == 0, cls.__name__
