"""Tests covering the BWB article semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.config.settings import RELATION_REFERS_TO_ARTICLE
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.bwb_articles import BwbArticlesSemanticPipeline


class FakeStore:
    def __init__(self, articles: dict[str, dict[str, Any]]) -> None:
        self._articles = articles
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        desired = []
        bwb_ids = bind_vars.get("bwb_ids") if bind_vars else None
        for article in self._articles.values():
            props = article.get("props", {})
            if bwb_ids and props.get("bwb_id") not in bwb_ids:
                continue
            if not props.get("text"):
                continue
            desired.append(article)
        return desired

    def get_node(self, collection: str, key: str) -> Node | None:
        doc = self._articles.get(key)
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

    def insert_or_update(self, node: Node) -> Node:
        if node.key is None:
            raise ValueError("Node must have a key to be updated.")
        doc = node.to_document()
        self._articles[node.key] = dict(doc)
        return Node.from_document(node.collection, self._articles[node.key])


def _make_article(
    key: str, bwb_id: str, article_number: str, text: str
) -> dict[str, Any]:
    return {
        "_key": key,
        "type": NodeType.ARTICLE.value,
        "labels": ["Article"],
        "props": {
            "bwb_id": bwb_id,
            "article_number": article_number,
            "text": text,
        },
    }


def _create_pipeline(
    store: FakeStore, store_citations: bool = False
) -> BwbArticlesSemanticPipeline:
    config = {
        "bwb": {
            "ids": ["BWBR0001854"],
        }
    }
    return BwbArticlesSemanticPipeline(
        store=store,
        domain_config=config,
        store_citations=store_citations,
    )


def test_pipeline_creates_refers_to_edges() -> None:
    source_key = make_node_key("BWBR0001854", "1")
    target_key = make_node_key("BWBR0001854", "24c")
    store = FakeStore(
        articles={
            source_key: _make_article(
                source_key,
                "BWBR0001854",
                "1",
                "Artikel 24c bevat een verwijzing.",
            ),
            target_key: _make_article(
                target_key,
                "BWBR0001854",
                "24c",
                "Geen verwijzingen hier.",
            ),
        }
    )

    pipeline = _create_pipeline(store)
    created = pipeline.run()

    assert created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_REFERS_TO_ARTICLE
    assert edge["_from"].split("/")[0] == "instrument_articles"
    assert edge["_to"].split("/")[0] == "instrument_articles"


def test_pipeline_is_idempotent() -> None:
    source_key = make_node_key("BWBR0001854", "1")
    target_key = make_node_key("BWBR0001854", "24c")
    store = FakeStore(
        articles={
            source_key: _make_article(
                source_key,
                "BWBR0001854",
                "1",
                "Artikel 24c wordt hernoemd.",
            ),
            target_key: _make_article(
                target_key,
                "BWBR0001854",
                "24c",
                "Doelartikel.",
            ),
        }
    )

    pipeline = _create_pipeline(store)
    first = pipeline.run()
    second = pipeline.run()

    assert first == 1
    assert second == 0
    assert len(store.edges) == 1


def test_pipeline_stores_citations_when_requested() -> None:
    source_key = make_node_key("BWBR0001854", "10")
    target_key = make_node_key("BWBR0001854", "15")
    store = FakeStore(
        articles={
            source_key: _make_article(
                source_key,
                "BWBR0001854",
                "10",
                "Artikel 15 staat vermeld.",
            ),
            target_key: _make_article(
                target_key,
                "BWBR0001854",
                "15",
                "Inspectie-artikel.",
            ),
        }
    )

    pipeline = _create_pipeline(store, store_citations=True)
    pipeline.run()

    updated = store._articles[source_key]["props"].get("citations") or []
    assert updated
    assert updated[0]["target_article_number"] == "15"
