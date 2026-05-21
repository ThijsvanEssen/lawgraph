"""Tests for the ECHR citations semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.models import Node, make_node_key
from lawgraph.pipelines.semantic.echr_citations import EchrCitationsPipeline


class _FakeStore:
    def __init__(
        self,
        *,
        judgment_rows: list[dict[str, Any]],
        instrument_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._judgment_rows = judgment_rows
        self._instrument_rows = instrument_rows or []
        self._nodes: dict[str, Node] = {}
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        if "judgments" in aql:
            return list(self._judgment_rows)
        if "instruments" in aql:
            return list(self._instrument_rows)
        return []

    def get_node(self, collection: str, key: str) -> Node | None:
        return self._nodes.get(f"{collection}/{key}")

    def insert_or_update(self, node: Node) -> Node:
        assert node.key is not None
        self._nodes[f"{node.collection}/{node.key}"] = node
        return node

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created


def test_pipeline_links_convention_articles() -> None:
    store = _FakeStore(
        judgment_rows=[
            {
                "j_id": "judgments/j1",
                "j_key": "j1",
                "articles": ["6", "8"],
                "conclusion": None,
            }
        ]
    )
    pipeline = EchrCitationsPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 2
    relations = {e["relation"] for e in store.edges.values()}
    assert "CITES_ARTICLE" in relations


def test_pipeline_creates_mentions_instrument_for_bwb_in_conclusion() -> None:
    bwb_id = "BWBR0001854"
    inst_key = make_node_key(bwb_id)
    store = _FakeStore(
        judgment_rows=[
            {
                "j_id": "judgments/j2",
                "j_key": "j2",
                "articles": [],
                "conclusion": f"De wet ({bwb_id}) is geschonden.",
            }
        ],
        instrument_rows=[{"_key": inst_key, "props": {"bwb_id": bwb_id}}],
    )
    pipeline = EchrCitationsPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created >= 1
    relations = {e["relation"] for e in store.edges.values()}
    assert "MENTIONS_INSTRUMENT" in relations


def test_pipeline_returns_empty_when_no_judgments() -> None:
    store = _FakeStore(judgment_rows=[])
    pipeline = EchrCitationsPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 0
