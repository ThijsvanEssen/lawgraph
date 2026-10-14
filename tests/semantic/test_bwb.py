"""Tests covering the BWB article semantic pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.models import NodeType, make_node_key
from lawgraph.core.relations import BY_NAME
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline
from tests.fakes import InMemoryStore, count_calls, patch_edge_removals


def _store(articles: dict[str, dict[str, Any]]) -> InMemoryStore:
    return InMemoryStore({"articles": articles.values()})


def _articles(store: InMemoryStore) -> list[dict[str, Any]]:
    return list(store.nodes["articles"].values())


@pytest.fixture(autouse=True)
def _article_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of the pipeline, answered from the articles of the fake store."""

    def article_bwb_ids(store: InMemoryStore) -> Iterator[str]:
        props = (article.get("props", {}) for article in _articles(store))
        return iter(dict.fromkeys(p["bwb_id"] for p in props if p.get("bwb_id")))

    def articles_with_references(
        store: InMemoryStore, bwb_ids: list[str]
    ) -> Iterator[dict[str, Any]]:
        return iter(
            article
            for article in _articles(store)
            if article.get("props", {}).get("bwb_id") in bwb_ids
            and article.get("props", {}).get("references") is not None
        )

    monkeypatch.setattr(semantic_bwb, "article_bwb_ids", article_bwb_ids)
    monkeypatch.setattr(
        semantic_bwb, "articles_with_references", articles_with_references
    )
    patch_edge_removals(monkeypatch)


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
    store: InMemoryStore, store_citations: bool = False
) -> BWBSemanticPipeline:
    return BWBSemanticPipeline(
        store=store,
        store_citations=store_citations,
    )


def _ref(bwb_id: str | None, article: str | None, text: str | None = None) -> dict:
    """A reference whose words name the article it links, unless *text* says otherwise."""
    text = text or f"artikel {article or '24c'}"
    return {
        "kind": "extref",
        "bwb_id": bwb_id,
        "article": article,
        "doc": f"jci1.3:c:{bwb_id}&artikel={article}",
        "text": text,
        "start": 4,
        "end": 4 + len(text),
    }


def _structured_store(
    refs: list[dict], text: str = "Zie artikel 24c hier."
) -> InMemoryStore:
    source = make_node_key("BWBR0001854", "1")
    same_law = make_node_key("BWBR0001854", "24c")
    other_law = make_node_key("BWBR0002222", "7")
    source_doc = _make_article(source, "BWBR0001854", "1", text)
    source_doc["props"]["references"] = refs
    return _store(
        {
            source: source_doc,
            same_law: _make_article(same_law, "BWBR0001854", "24c", "Doel."),
            other_law: _make_article(other_law, "BWBR0002222", "7", "Ander doel."),
        }
    )


def test_pipeline_creates_refers_to_edges_between_articles() -> None:
    store = _structured_store([_ref("BWBR0001854", "24c")])

    result = _create_pipeline(store).run()

    assert result.created == 1
    (edge,) = store.edges.values()
    assert edge["relation"] == RELATION_REFERS_TO
    spec = BY_NAME[RELATION_REFERS_TO]
    assert edge["_from"].split("/")[0] in spec.sources
    assert edge["_to"].split("/")[0] in spec.targets


def test_pipeline_is_idempotent() -> None:
    store = _structured_store([_ref("BWBR0001854", "24c")])
    pipeline = _create_pipeline(store)

    first = pipeline.run()
    second = pipeline.run()

    assert (first.created, second.created) == (1, 0)
    assert len(store.edges) == 1


def test_structured_references_create_exact_edges_across_laws() -> None:
    store = _structured_store([_ref("BWBR0002222", "7", "artikel 7 van die wet")])

    result = _create_pipeline(store).run()

    assert result.created == 1
    (edge,) = store.edges.values()
    assert edge["_to"] == f"articles/{make_node_key('BWBR0002222', '7')}"
    assert edge["confidence"] == 1.0
    assert edge["meta"] == {
        "start": 4,
        "end": 4 + len("artikel 7 van die wet"),
        "text": "artikel 7 van die wet",
        "reason": "bwb_xml_ref",
        "reference_kind": "extref",
        "leden": [],
        "onderdelen": [],
        "aanhef": False,
    }


def test_the_edge_carries_the_lid_and_onderdeel_the_reference_names() -> None:
    text = "artikel 24c, tweede lid, aanhef en onder b"
    ref = {**_ref("BWBR0001854", "24c", text), "kind": "intref"}
    ref.update(leden=["2"], onderdelen=["b"], aanhef=True)
    store = _structured_store([ref])

    _create_pipeline(store).run()

    (edge,) = store.edges.values()
    assert edge["meta"]["reference_kind"] == "intref"
    assert edge["meta"]["leden"] == ["2"]
    assert edge["meta"]["onderdelen"] == ["b"]
    assert edge["meta"]["aanhef"] is True


def test_article_text_alone_creates_no_edge() -> None:
    """The text says "artikel 24c" but the XML records no reference."""
    store = _structured_store([])

    assert _create_pipeline(store).run().created == 0
    assert not store.edges


def test_articles_without_references_are_not_scanned() -> None:
    store = _structured_store([])
    del store.nodes["articles"][make_node_key("BWBR0001854", "1")]["props"][
        "references"
    ]

    assert _create_pipeline(store).run().created == 0
    assert not store.edges


def test_structured_references_skip_self_incomplete_and_unknown_targets() -> None:
    store = _structured_store(
        [
            _ref("BWBR0001854", "1"),  # the article itself
            _ref(None, "24c"),  # no regulation
            _ref("BWBR0001854", None),  # no article
            _ref("BWBR0009999", "1"),  # target not in the graph
            _ref("BWBR0001854", "24c"),  # the only usable one
        ]
    )

    result = _create_pipeline(store).run()

    assert result.created == 1
    (edge,) = store.edges.values()
    assert edge["_to"].endswith(make_node_key("BWBR0001854", "24c"))


def test_the_words_of_a_reference_win_over_a_link_to_another_article() -> None:
    store = _structured_store([_ref("BWBR0001854", "24", "artikel 24c")])

    _create_pipeline(store).run()

    (edge,) = store.edges.values()
    assert edge["_to"].endswith(make_node_key("BWBR0001854", "24c"))
    assert edge["meta"]["linked_article"] == make_node_key("BWBR0001854", "24")


def test_the_link_counts_when_the_graph_lacks_the_article_the_words_name() -> None:
    store = _structured_store([_ref("BWBR0001854", "24c", "artikel 24clid 1")])

    _create_pipeline(store).run()

    (edge,) = store.edges.values()
    assert edge["_to"].endswith(make_node_key("BWBR0001854", "24c"))
    assert "linked_article" not in edge["meta"]


def test_store_citations_records_the_structured_references() -> None:
    store = _structured_store([_ref("BWBR0002222", "7")])

    _create_pipeline(store, store_citations=True).run()

    source = store.nodes["articles"][make_node_key("BWBR0001854", "1")]
    (citation,) = source["props"]["citations"]
    assert citation["target_bwb_id"] == "BWBR0002222"
    assert citation["target_article_number"] == "7"
    assert citation["confidence"] == 1.0
    # the partial upsert must not clobber the article text
    assert source["props"]["text"] == "Zie artikel 24c hier."


def test_structured_references_resolve_targets_in_bulk() -> None:
    n = 30
    articles = {}
    for i in range(1, n + 1):
        key = make_node_key("BWBR0001854", str(i))
        articles[key] = _make_article(key, "BWBR0001854", str(i), "Zie het volgende.")
        articles[key]["props"]["references"] = [
            _ref("BWBR0001854", "1"),
            _ref("BWBR0001854", "2"),
        ]
    store = _store(articles)
    calls = count_calls(store, "get_node", "existing_keys")

    _create_pipeline(store).run()

    assert calls["get_node"] == 0  # everything came from the bulk prefetch
    assert calls["existing_keys"] == 1  # 30 articles, one chunk, one lookup
    assert len(store.edges) == 2 * n - 2  # everyone -> 1 and 2, minus the self loops
