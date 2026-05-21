"""Tests for the BWB grondslagen semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.models import make_node_key
from lawgraph.pipelines.semantic.bwb_grondslagen import (
    BWBGrondslagenSemanticPipeline,
    _extract_grondslagen,
)

# ---------------------------------------------------------------------------
# XML extraction helper
# ---------------------------------------------------------------------------

_TOESTAND_XML = """<?xml version="1.0"?>
<wet>
  <grondslagen>
    <grondslag>
      <extref doc="BWBR0001854">artikel 5</extref>
    </grondslag>
  </grondslagen>
</wet>
"""

_TOESTAND_XML_TEXT_ONLY = """<?xml version="1.0"?>
<wet>
  <grondslagen>
    <grondslag>
      <al>Gebaseerd op artikel 3 van BWBR0011823.</al>
    </grondslag>
  </grondslagen>
</wet>
"""


def test_extract_grondslagen_from_extref() -> None:
    results = _extract_grondslagen(_TOESTAND_XML)
    assert len(results) == 1
    g = results[0]
    assert g["bwb_ref"] == "BWBR0001854"
    assert "5" in g["article_labels"]


def test_extract_grondslagen_from_text_bwb_id() -> None:
    results = _extract_grondslagen(_TOESTAND_XML_TEXT_ONLY)
    assert len(results) == 1
    g = results[0]
    assert g["bwb_ref"] == "BWBR0011823"
    assert "3" in g["article_labels"]


def test_extract_grondslagen_empty_xml() -> None:
    results = _extract_grondslagen("<wet><body>geen grondslagen</body></wet>")
    assert results == []


def test_extract_grondslagen_invalid_xml() -> None:
    results = _extract_grondslagen("not xml at all")
    assert results == []


# ---------------------------------------------------------------------------
# Pipeline smoke test
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(
        self,
        *,
        raw_rows: list[dict[str, Any]],
        instrument_docs: list[dict[str, Any]] | None = None,
        article_docs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._raw_rows = raw_rows
        self._instrument_docs = instrument_docs or []
        self._article_docs = article_docs or []
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        if "raw_sources" in aql:
            return list(self._raw_rows)
        if "instrument_articles" in aql:
            return list(self._article_docs)
        if "instruments" in aql:
            return list(self._instrument_docs)
        return []

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created


def test_pipeline_creates_delegated_by_edge() -> None:
    amvb_bwb_id = "BWBR0011823"
    parent_bwb_id = "BWBR0001854"
    amvb_key = make_node_key(amvb_bwb_id)
    article_key = make_node_key(parent_bwb_id, "5")

    xml = f"""<wet><grondslagen><grondslag>
      <extref doc="{parent_bwb_id}">artikel 5</extref>
    </grondslag></grondslagen></wet>"""

    store = _FakeStore(
        raw_rows=[{"bwb_id": amvb_bwb_id, "xml": xml}],
        instrument_docs=[{"_key": amvb_key, "props": {"bwb_id": amvb_bwb_id}}],
        article_docs=[
            {
                "_key": article_key,
                "props": {"bwb_id": parent_bwb_id, "article_number": "5"},
            }
        ],
    )
    pipeline = BWBGrondslagenSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "DELEGATED_BY"
    assert edge["_from"].startswith("instruments/")
    assert edge["_to"].startswith("instrument_articles/")


def test_pipeline_returns_empty_when_no_raw_rows() -> None:
    store = _FakeStore(raw_rows=[])
    pipeline = BWBGrondslagenSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 0
    assert len(store.edges) == 0
