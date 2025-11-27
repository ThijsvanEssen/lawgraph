"""Tests for the EU article semantic linker."""

from __future__ import annotations

from typing import Any

from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.eu_articles import (
    EUArticleSemanticPipeline,
    detect_eu_citations,
)


def _make_instrument(key: str, celex: str | None = None, html: str | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if celex:
        props["celex"] = celex
    if html:
        props["raw_html"] = html
    return {
        "_key": key,
        "labels": ["EU"],
        "type": NodeType.INSTRUMENT.value,
        "props": props,
    }


def _make_bwb_article(key: str, article_props: dict[str, Any]) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["Article"],
        "type": NodeType.ARTICLE.value,
        "props": article_props,
    }


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
        return list(self._documents)

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


def test_detect_eu_citations_richtlijn_article() -> None:
    text = "Artikel 6 van Richtlijn 2010/13/EU"
    hits = detect_eu_citations(text, {"Sr": "BWBR0001854"})
    assert hits
    assert any(hit.celex == "32010L0013" for hit in hits)
    cine = [hit for hit in hits if hit.celex == "32010L0013"]
    assert cine[0].kind == "article"


def test_detect_eu_citations_bwb_article_alias() -> None:
    hits = detect_eu_citations("zoals bedoeld in artikel 287 Sr", {"Sr": "BWBR0001854"})
    assert hits
    assert any(hit.bwb_id == "BWBR0001854" and hit.article_number == "287" for hit in hits)


def test_eu_pipeline_links_celex_target() -> None:
    source_key = "eu-source"
    target_key = make_node_key("32019L1158")
    source_doc = _make_instrument(source_key, html="<p>Implementing act under CELEX:32019L1158</p>")
    target_doc = _make_instrument(target_key, celex="32019L1158")
    store = FakeStore(
        documents=[source_doc],
        instruments={target_key: target_doc},
        articles={},
    )
    pipeline = EUArticleSemanticPipeline(
        store=store,
        domain_config={"code_aliases": {"Sr": "BWBR0001854"}},
    )

    created = pipeline.run()
    assert created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "MENTIONS_ARTICLE"
    assert edge["source"] == "eu-article-linker"
    assert edge["_to"].startswith("instruments/")


def test_eu_pipeline_links_bwb_article() -> None:
    source_key = "eu-source-2"
    doc = _make_instrument(source_key, html="<p>zoals bedoeld in artikel 287 Sr</p>")
    article_key = make_node_key("BWBR0001854", "287")
    article_doc = _make_bwb_article(article_key, {"bwb_id": "BWBR0001854", "article_number": "287"})
    store = FakeStore(
        documents=[doc],
        instruments={},
        articles={article_key: article_doc},
    )
    pipeline = EUArticleSemanticPipeline(
        store=store,
        domain_config={"code_aliases": {"Sr": "BWBR0001854"}},
    )

    created = pipeline.run()
    assert created == 1
    edge = next(iter(store.edges.values()))
    assert edge["_to"].startswith("instrument_articles/")


def test_eu_pipeline_idempotent_edges() -> None:
    source_key = "eu-source-3"
    doc = _make_instrument(source_key, html="<p>Implementing act under CELEX:32019L1158</p>")
    target_key = make_node_key("32019L1158")
    target_doc = _make_instrument(target_key, celex="32019L1158")
    store = FakeStore(
        documents=[doc],
        instruments={target_key: target_doc},
        articles={},
    )
    pipeline = EUArticleSemanticPipeline(
        store=store,
        domain_config={"code_aliases": {}},
    )

    first = pipeline.run()
    second = pipeline.run()
    assert first == 1
    assert second == 0
    assert len(store.edges) == 1
    key = next(iter(store.edges))
    expected_key = (
        f"{make_node_key(source_key)}__{make_node_key(target_key)}__MENTIONS_ARTICLE"
    )
    assert key == expected_key
