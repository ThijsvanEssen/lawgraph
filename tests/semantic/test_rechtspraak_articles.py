from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.citations import detect_article_references
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.base import CodeMapping
from lawgraph.pipelines.semantic.rechtspraak_articles import (
    RechtspraakArticlesSemanticPipeline,
)
from tests.conftest import _BaseFakeStore


class _FakeStore(_BaseFakeStore):
    def __init__(
        self,
        judgments: list[dict[str, Any]],
        articles: dict[str, dict[str, Any]],
        instruments: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._judgments = judgments
        self._articles = articles
        self._instruments = instruments or []

    def query(
        self, aql: str, bind_vars: dict | None = None, **_kw: Any
    ) -> list[dict[str, Any]]:
        if "FOR doc IN judgments" in aql:
            return list(self._judgments)
        if "FOR inst IN instruments" in aql:
            return list(self._instruments)
        return []

    def get_node(self, collection: str, key: str) -> Node | None:
        doc = self._articles.get(key)
        if doc is None:
            return None
        return Node.from_document(collection, doc)

    def insert_or_update_edge(
        self,
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
    # Provide an instrument with short_title so _load_code_aliases finds "Sr".
    instrument_row = {
        "short_title": "Sr",
        "bwb_id": "BWBR0001854",
        "celex": None,
    }
    store = _FakeStore(
        judgments=[judgment_doc],
        articles={article_doc["_key"]: article_doc},
        instruments=[instrument_row],
    )
    pipeline = RechtspraakArticlesSemanticPipeline(store=store)

    created_first = pipeline.run()
    assert created_first.created == 1
    assert len(store.edges) == 1

    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_REFERS_TO
    assert edge["source"] == "rechtspraak-article-linker"
    assert isinstance(edge["confidence"], float)

    created_second = pipeline.run()
    assert created_second.created == 0
    assert len(store.edges) == 1


def _judgment(text: str) -> dict[str, Any]:
    doc = _make_judgment_doc()
    doc["props"]["raw_xml"] = text
    return doc


def _edges(text: str, instruments: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    articles = {
        make_node_key("BWBR0005537", "8:29"): {
            "_key": make_node_key("BWBR0005537", "8:29"),
            "type": NodeType.ARTICLE.value,
            "props": {"bwb_id": "BWBR0005537", "article_number": "8:29"},
        }
    }
    store = _FakeStore(
        judgments=[_judgment(text)], articles=articles, instruments=instruments
    )
    RechtspraakArticlesSemanticPipeline(store=store).run()
    return store.edges


def test_a_judgment_citing_an_article_of_a_law_by_its_name_is_linked() -> None:
    instruments = [
        {
            "bwb_id": "BWBR0005537",
            "celex": None,
            "title": "Algemene wet bestuursrecht",
            "citation_title": None,
        }
    ]
    edges = _edges(
        "Volgens artikel 8:29, eerste lid, van de Algemene wet bestuursrecht moet",
        instruments,
    )
    assert len(edges) == 1
    assert next(iter(edges.values()))["meta"]["qualifier"] == "eerste lid"


def test_a_title_two_laws_share_is_no_alias() -> None:
    instruments = [
        {
            "bwb_id": "BWBR0005537",
            "celex": None,
            "title": "Wet gelijk",
            "citation_title": None,
        },
        {
            "bwb_id": "BWBR0001854",
            "celex": None,
            "title": "Wet gelijk",
            "citation_title": None,
        },
    ]
    assert _edges("artikel 8:29 van de Wet gelijk", instruments) == {}
