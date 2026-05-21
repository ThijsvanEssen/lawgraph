"""Tests for the judgment-citations semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.judgment_citations import (
    JudgmentCitationsSemanticPipeline,
    detect_ecli_references,
)

# ---------------------------------------------------------------------------
# Pure detection helper
# ---------------------------------------------------------------------------


def test_detect_ecli_references_finds_single() -> None:
    hits = detect_ecli_references("Zie ECLI:NL:HR:2020:1234 voor context.")
    assert hits == ["ECLI:NL:HR:2020:1234"]


def test_detect_ecli_references_deduplicates() -> None:
    text = "ECLI:NL:HR:2020:1234 en nogmaals ECLI:NL:HR:2020:1234"
    hits = detect_ecli_references(text)
    assert hits == ["ECLI:NL:HR:2020:1234"]


def test_detect_ecli_references_multiple() -> None:
    text = "ECLI:NL:HR:2020:1234 en ECLI:NL:RBAMS:2021:5678"
    hits = detect_ecli_references(text)
    assert len(hits) == 2


def test_detect_ecli_references_empty() -> None:
    assert detect_ecli_references("") == []
    assert detect_ecli_references(None) == []


# ---------------------------------------------------------------------------
# Pipeline smoke test
# ---------------------------------------------------------------------------


class _FakeStore:
    def __init__(
        self,
        *,
        judgment_docs: list[dict[str, Any]],
        nodes: dict[tuple[str, str], Node] | None = None,
    ) -> None:
        self._judgment_docs = judgment_docs
        self._nodes = nodes or {}
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        # Secondary ECLI lookup — return nothing (we populate via get_node).
        if "props.ecli" in aql:
            return []
        return list(self._judgment_docs)

    def get_node(self, collection: str, key: str) -> Node | None:
        return self._nodes.get((collection, key))

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created

    def ensure_stub_node(
        self,
        collection: str,
        key: str,
        node_type: NodeType,
        props: dict[str, Any],
    ) -> Node:
        node = Node(
            collection=collection,
            type=node_type,
            key=key,
            props=props,
            _skip_validation=True,
        )
        self._nodes[(collection, key)] = node
        return node


def _make_judgment(key: str, ecli: str, text: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_id": f"judgments/{key}",
        "type": NodeType.JUDGMENT.value,
        "labels": [],
        "props": {"ecli": ecli, "raw_xml": text},
    }


def test_pipeline_creates_cites_judgment_edge() -> None:
    source_ecli = "ECLI:NL:HR:2020:1234"
    target_ecli = "ECLI:NL:HR:2019:9876"
    source_doc = _make_judgment(
        make_node_key(source_ecli),
        source_ecli,
        f"Zie het arrest {target_ecli} voor de onderbouwing.",
    )
    target_key = make_node_key(target_ecli)
    target_node = Node(
        collection="judgments",
        type=NodeType.JUDGMENT,
        key=target_key,
        props={"ecli": target_ecli},
        _skip_validation=True,
    )
    store = _FakeStore(
        judgment_docs=[source_doc],
        nodes={("judgments", target_key): target_node},
    )
    pipeline = JudgmentCitationsSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "CITES_JUDGMENT"
    assert edge["_from"].startswith("judgments/")
    assert edge["_to"].startswith("judgments/")


def test_pipeline_skips_self_reference() -> None:
    ecli = "ECLI:NL:HR:2020:1234"
    doc = _make_judgment(
        make_node_key(ecli), ecli, f"Dit arrest ({ecli}) overweegt dat..."
    )
    store = _FakeStore(judgment_docs=[doc])
    pipeline = JudgmentCitationsSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 0
