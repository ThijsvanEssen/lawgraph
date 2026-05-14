"""Tests for dossier-related semantic pipelines:
DossierLawLink, EerstekamerDossierLink, StaatsbladNvt, StaatscourantRegeling.
"""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.semantic.dossier_law_link import DossierLawLinkPipeline
from lawgraph.pipelines.semantic.eerstekamer_dossier_link import (
    EerstekamerDossierLinkPipeline,
)
from lawgraph.pipelines.semantic.staatsblad_nvt import StaatsbladNvtSemanticPipeline
from lawgraph.pipelines.semantic.staatscourant_regeling import (
    StaatscourantRegelingSemanticPipeline,
)


class _FakeStore:
    """Generic FakeStore that returns pre-set query results."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        return list(self._rows)

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created


# ---------------------------------------------------------------------------
# DossierLawLinkPipeline
# ---------------------------------------------------------------------------


def test_dossier_law_link_creates_resulted_in_edge() -> None:
    rows = [
        {
            "dos_id": "kamerstukdossiers/36000",
            "dos_key": "36000",
            "inst_id": "instruments/bwbr0001854",
            "inst_key": "bwbr0001854",
            "match_type": "citation_title",
        }
    ]
    store = _FakeStore(rows=rows)
    pipeline = DossierLawLinkPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "RESULTED_IN"
    assert edge["confidence"] == 0.90


def test_dossier_law_link_deduplicates_pairs() -> None:
    row = {
        "dos_id": "kamerstukdossiers/36000",
        "dos_key": "36000",
        "inst_id": "instruments/bwbr0001854",
        "inst_key": "bwbr0001854",
        "match_type": "citation_title",
    }
    store = _FakeStore(rows=[row, row])
    pipeline = DossierLawLinkPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 1


def test_dossier_law_link_returns_empty_when_no_rows() -> None:
    store = _FakeStore(rows=[])
    pipeline = DossierLawLinkPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 0


# ---------------------------------------------------------------------------
# EerstekamerDossierLinkPipeline
# ---------------------------------------------------------------------------


def test_ek_dossier_link_creates_deel_van_dossier_edge() -> None:
    rows = [
        {
            "pub_id": "publications/ek-stuk-1",
            "pub_key": "ek-stuk-1",
            "dos_id": "kamerstukdossiers/36000",
            "dos_key": "36000",
            "dossier_nummer": "36000",
        }
    ]
    store = _FakeStore(rows=rows)
    pipeline = EerstekamerDossierLinkPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "DEEL_VAN_DOSSIER"
    assert edge["confidence"] == 0.95


def test_ek_dossier_link_returns_empty_when_no_rows() -> None:
    store = _FakeStore(rows=[])
    pipeline = EerstekamerDossierLinkPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 0


# ---------------------------------------------------------------------------
# StaatsbladNvtSemanticPipeline
# ---------------------------------------------------------------------------


def test_staatsblad_nvt_creates_explains_instrument_edge() -> None:
    rows = [
        {
            "pub_id": "publications/stbl-1",
            "pub_key": "stbl-1",
            "inst_id": "instruments/bwbr0001854",
            "inst_key": "bwbr0001854",
            "match_type": "bwb_id",
        }
    ]
    store = _FakeStore(rows=rows)
    pipeline = StaatsbladNvtSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "EXPLAINS_INSTRUMENT"
    assert edge["confidence"] == 0.85


# ---------------------------------------------------------------------------
# StaatscourantRegelingSemanticPipeline
# ---------------------------------------------------------------------------


def test_staatscourant_regeling_creates_explains_instrument_edge() -> None:
    rows = [
        {
            "pub_id": "publications/stcrt-1",
            "pub_key": "stcrt-1",
            "inst_id": "instruments/bwbr0001854",
            "inst_key": "bwbr0001854",
            "match_type": "bwb_id",
        }
    ]
    # The pipeline calls query three times: bwb query, title query, text-scan query.
    # All return the same row — dedup ensures only 1 edge is created.
    store = _FakeStore(rows=rows)
    pipeline = StaatscourantRegelingSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "EXPLAINS_INSTRUMENT"
    assert edge["confidence"] == 0.92
