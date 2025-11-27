"""Tests for the TK article semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.tk_articles import (
    TKArticleSemanticPipeline,
    detect_tk_citations,
)


class FakeStore:
    def __init__(
        self,
        documents: list[dict[str, Any]],
        instruments: dict[str, dict[str, Any]],
        articles: dict[str, dict[str, Any]],
    ) -> None:
        self._documents = documents
        self._instruments = instruments
        self._articles = articles
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        if "FOR doc IN publications" in aql:
            return list(self._documents)
        if "FOR doc IN procedures" in aql:
            return []
        return []

    def get_node(self, collection: str, key: str) -> Node | None:
        docs = self._instruments if collection == "instruments" else self._articles
        doc = docs.get(key)
        if doc is None:
            return None
        return Node.from_document(collection, doc)

    def insert_or_update_edge(
        self,
        *,
        collection_name: str,
        doc: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        key = doc["_key"]
        created = key not in self.edges
        self.edges[key] = dict(doc)
        return self.edges[key], created


def _make_tk_document(key: str, text: str) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["TK", "Strafrecht"],
        "type": NodeType.PUBLICATION.value,
        "props": {
            "raw": {"Tekst": text},
            "title": text,
        },
    }


def _make_instrument(key: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["Instrument"],
        "type": NodeType.INSTRUMENT.value,
        "props": props,
    }


def _make_article(key: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["Article"],
        "type": NodeType.ARTICLE.value,
        "props": props,
    }


def _load_config() -> dict[str, Any]:
    return {
        "code_aliases": {"Sr": "BWBR0001854"},
        "instrument_aliases": {"Wetboek van Strafrecht": "BWBR0001854"},
    }


def test_detect_tk_citations_include_article_alias() -> None:
    text = "Wijziging van artikel 287 Sr"
    hits = detect_tk_citations(text, _load_config()["code_aliases"], _load_config()["instrument_aliases"])
    assert hits
    article_hits = [hit for hit in hits if hit.kind == "article"]
    assert article_hits
    assert article_hits[0].bwb_id == "BWBR0001854"
    assert article_hits[0].article_number == "287"


def test_tk_pipeline_links_to_article_node() -> None:
    doc = _make_tk_document("tk-1", "Wijziging van artikel 287 Sr")
    article_key = make_node_key("BWBR0001854", "287")
    article = _make_article(article_key, {"bwb_id": "BWBR0001854", "article_number": "287"})
    store = FakeStore(
        documents=[doc],
        instruments={make_node_key("BWBR0001854"): _make_instrument(make_node_key("BWBR0001854"), {"bwb_id": "BWBR0001854"})},
        articles={article_key: article},
    )
    pipeline = TKArticleSemanticPipeline(
        store=store,
        domain_config=_load_config(),
    )

    created = pipeline.run()
    assert created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "MENTIONS_ARTICLE"
    assert edge["source"] == "tk-article-linker"
    assert isinstance(edge["confidence"], float)


def test_tk_pipeline_links_to_celex_instrument() -> None:
    text = "Implementatie van CELEX:32019L1158"
    doc = _make_tk_document("tk-2", text)
    celex_key = make_node_key("32019L1158")
    instrument = _make_instrument(celex_key, {"celex": "32019L1158"})
    store = FakeStore(
        documents=[doc],
        instruments={celex_key: instrument},
        articles={},
    )
    pipeline = TKArticleSemanticPipeline(
        store=store,
        domain_config=_load_config(),
    )

    created = pipeline.run()
    assert created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["_to"].split("/")[0] == "instruments"


def test_tk_pipeline_links_named_act_to_instrument() -> None:
    text = "Deze wijziging betreft het Wetboek van Strafrecht."
    doc = _make_tk_document("tk-3", text)
    instr_key = make_node_key("BWBR0001854")
    instrument = _make_instrument(instr_key, {"bwb_id": "BWBR0001854"})
    store = FakeStore(
        documents=[doc],
        instruments={instr_key: instrument},
        articles={},
    )
    pipeline = TKArticleSemanticPipeline(
        store=store,
        domain_config=_load_config(),
    )

    created = pipeline.run()
    assert created == 1
    assert len(store.edges) == 1


def test_tk_pipeline_idempotent_edges() -> None:
    doc = _make_tk_document("tk-4", "Wijziging van artikel 287 Sr")
    article_key = make_node_key("BWBR0001854", "287")
    article = _make_article(article_key, {"bwb_id": "BWBR0001854", "article_number": "287"})
    store = FakeStore(
        documents=[doc],
        instruments={make_node_key("BWBR0001854"): _make_instrument(make_node_key("BWBR0001854"), {"bwb_id": "BWBR0001854"})},
        articles={article_key: article},
    )
    pipeline = TKArticleSemanticPipeline(
        store=store,
        domain_config=_load_config(),
    )

    first = pipeline.run()
    second = pipeline.run()
    assert first == 1
    assert second == 0
    assert len(store.edges) == 1
