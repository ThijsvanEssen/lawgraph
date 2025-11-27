from __future__ import annotations

from typing import Any

from lawgraph.cli.semantic_rechtspraak_articles import (
    RechtspraakArticleSemanticPipeline,
)
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.rechtspraak_articles import (
    CodeMapping,
    detect_article_references,
)


class FakeStore:
    def __init__(
        self, judgments: list[dict[str, Any]], articles: dict[str, dict[str, Any]]
    ) -> None:
        self._judgments = judgments
        self._articles = articles
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        if "FOR doc IN judgments" in aql:
            return list(self._judgments)
        return []

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


def _make_judgment_doc() -> dict[str, Any]:
    return {
        "_key": "hr-2019-793",
        "labels": ["Rechtspraak"],
        "type": NodeType.JUDGMENT.value,
        "props": {
            "raw_xml": "Dit is een tekst met art. 287 Sr en art. 287 Sr.",
            "meta": {"ecli": "ECLI:NL:HR:2019:793"},
        },
    }


def _make_article_doc() -> dict[str, Any]:
    return {
        "_key": make_node_key("BWBR0001854", "287"),
        "labels": ["BWB", "Article"],
        "type": NodeType.ARTICLE.value,
        "props": {
            "bwb_id": "BWBR0001854",
            "article_number": "287",
        },
    }


def test_detect_article_references_alias_mapping() -> None:
    mapping: CodeMapping = {
        "Sr": "BWBR0001854",
        "Sv": "BWBR0001903",
        "WVW": "BWBR0006622",
    }
    hits = detect_article_references("art. 287 Sr", mapping)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.bwb_id == "BWBR0001854"
    assert hit.article_number == "287"
    assert abs(hit.confidence - 0.95) < 0.01


def test_detect_article_references_wvw_mapping() -> None:
    mapping: CodeMapping = {"WVW": "BWBR0006622"}
    hits = detect_article_references("artikel 185 WVW", mapping)
    assert hits and hits[0].bwb_id == "BWBR0006622"


def test_detect_article_references_no_alias_lower_confidence() -> None:
    mapping: CodeMapping = {"Sr": "BWBR0001854"}
    hits = detect_article_references("artikel 287", mapping)
    assert hits
    assert hits[0].confidence < 0.5


def test_rechtspraak_article_semantic_pipeline_idempotent_edges() -> None:
    judgment_doc = _make_judgment_doc()
    article_doc = _make_article_doc()
    store = FakeStore(
        judgments=[judgment_doc],
        articles={article_doc["_key"]: article_doc},
    )
    config = {"code_aliases": {"Sr": "BWBR0001854"}}
    pipeline = RechtspraakArticleSemanticPipeline(
        store=store,
        domain_config=config,
    )

    created_first = pipeline.run()
    assert created_first == 1
    assert len(store.edges) == 1

    key = next(iter(store.edges))
    expected_key = (
        f"{make_node_key(judgment_doc['_key'])}"
        f"__{make_node_key(article_doc['_key'])}__MENTIONS_ARTICLE"
    )
    assert key == expected_key
    edge = store.edges[key]
    assert edge["relation"] == "MENTIONS_ARTICLE"
    assert edge["source"] == "rechtspraak-article-linker"
    assert not edge["strict"]
    assert isinstance(edge["confidence"], float)

    created_second = pipeline.run()
    assert created_second == 0
    assert len(store.edges) == 1
