"""Tests for dossier-related semantic pipelines:
StaatsbladNvt, StaatscourantRegeling.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_EXPLAINS
from lawgraph.pipelines.semantic.staatsblad_nvt import StaatsbladNvtSemanticPipeline
from lawgraph.pipelines.semantic.staatscourant_regeling import (
    StaatscourantRegelingSemanticPipeline,
)
from tests.conftest import _BaseFakeStore


class _FakeStore(_BaseFakeStore):
    """Generic FakeStore that returns pre-set query results."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self._rows = rows

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        return list(self._rows)


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# StaatsbladNvtSemanticPipeline
# ---------------------------------------------------------------------------


def test_staatsblad_nvt_creates_explains_instrument_edge() -> None:
    rows = [
        {
            "pub_id": "documents/stbl-1",
            "pub_key": "stbl-1",
            "inst_id": "instruments/bwbr0001854",
            "inst_key": "bwbr0001854",
            "match_type": "bwb_id",
        }
    ]
    store = _FakeStore(rows=rows)
    pipeline = StaatsbladNvtSemanticPipeline(store=store)
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_EXPLAINS
    assert edge["confidence"] == 0.85


# ---------------------------------------------------------------------------
# StaatscourantRegelingSemanticPipeline
# ---------------------------------------------------------------------------


def test_staatscourant_regeling_creates_explains_instrument_edge() -> None:
    rows = [
        {
            "pub_id": "documents/stcrt-1",
            "pub_key": "stcrt-1",
            "inst_id": "instruments/bwbr0001854",
            "inst_key": "bwbr0001854",
            "match_type": "bwb_id",
        }
    ]
    # The pipeline calls query three times: bwb query, title query, text-scan query.
    # All return the same row — dedup ensures only 1 edge is created.
    store = _FakeStore(rows=rows)
    pipeline = StaatscourantRegelingSemanticPipeline(store=store)
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_EXPLAINS
    assert edge["confidence"] == 0.92


def test_semantic_edges_are_written_in_bulk_batches() -> None:
    """1200 document/instrument pairs -> a handful of bulk calls, not 1200 writes."""
    rows = [
        {
            "pub_id": f"documents/stbl-{n}",
            "pub_key": f"stbl-{n}",
            "inst_id": "instruments/bwbr0001854",
            "inst_key": "bwbr0001854",
            "match_type": "bwb_id",
        }
        for n in range(1200)
    ]

    class _CountingStore(_FakeStore):
        bulk_calls = 0

        def bulk_insert_or_update_edges(self, docs):
            type(self).bulk_calls += 1
            return super().bulk_insert_or_update_edges(docs)

    store = _CountingStore(rows=rows)
    result = StaatsbladNvtSemanticPipeline(store=store).run()

    assert result.created == 1200
    assert len(store.edges) == 1200
    assert store.bulk_calls == 2  # 1000 + 200: the batches of `EdgeWriter`
