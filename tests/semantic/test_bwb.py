"""Tests covering the BWB article semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.relations import BY_NAME
from lawgraph.pipelines.semantic.bwb import BWBSemanticPipeline
from tests.conftest import _BaseFakeStore


class _FakeStore(_BaseFakeStore):
    def __init__(self, articles: dict[str, dict[str, Any]]) -> None:
        super().__init__()
        self._articles = articles

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        if "RETURN DISTINCT" in aql and "bwb_id" in aql and not bind_vars:
            seen = set()
            result = []
            for article in self._articles.values():
                bwb_id = article.get("props", {}).get("bwb_id")
                if bwb_id and bwb_id not in seen:
                    seen.add(bwb_id)
                    result.append(bwb_id)
            return result
        desired = []
        bwb_ids = bind_vars.get("bwb_ids") if bind_vars else None
        for article in self._articles.values():
            props = article.get("props", {})
            if bwb_ids and props.get("bwb_id") not in bwb_ids:
                continue
            if props.get("references") is None:
                continue
            desired.append(article)
        return desired

    def get_node(self, collection: str, key: str) -> Node | None:
        doc = self._articles.get(key)
        if doc is None:
            return None
        return Node.from_document(collection, doc)

    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        created, updated = 0, 0
        for doc in docs:
            was_new = doc["_key"] not in self.edges
            self.edges[doc["_key"]] = dict(doc)
            if was_new:
                created += 1
            else:
                updated += 1
        return created, updated

    def existing_keys(self, collection: str, keys) -> set[str]:
        self.existence_calls = getattr(self, "existence_calls", 0) + 1
        return set(keys) & set(self._articles)

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Merge props like the real upsert does (partial docs keep other props)."""
        for doc in docs:
            stored = self._articles[doc["_key"]]
            stored["props"] = {**stored["props"], **doc["props"]}
        return 0, len(docs)


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
    store: _FakeStore, store_citations: bool = False
) -> BWBSemanticPipeline:
    return BWBSemanticPipeline(
        store=store,
        store_citations=store_citations,
    )


def _ref(bwb_id: str | None, article: str | None, text: str = "artikel 24c") -> dict:
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
) -> _FakeStore:
    source = make_node_key("BWBR0001854", "1")
    same_law = make_node_key("BWBR0001854", "24c")
    other_law = make_node_key("BWBR0002222", "7")
    source_doc = _make_article(source, "BWBR0001854", "1", text)
    source_doc["props"]["references"] = refs
    return _FakeStore(
        articles={
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
    }


def test_article_text_alone_creates_no_edge() -> None:
    """The text says "artikel 24c" but the XML records no reference."""
    store = _structured_store([])

    assert _create_pipeline(store).run().created == 0
    assert not store.edges


def test_articles_without_references_are_not_scanned() -> None:
    store = _structured_store([])
    del store._articles[make_node_key("BWBR0001854", "1")]["props"]["references"]

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


def test_store_citations_records_the_structured_references() -> None:
    store = _structured_store([_ref("BWBR0002222", "7")])

    _create_pipeline(store, store_citations=True).run()

    source = store._articles[make_node_key("BWBR0001854", "1")]
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
    store = _FakeStore(articles=articles)
    store.get_node_calls = 0
    original_get_node = store.get_node

    def counting_get_node(collection: str, key: str):
        store.get_node_calls += 1
        return original_get_node(collection, key)

    store.get_node = counting_get_node  # type: ignore[method-assign]

    _create_pipeline(store).run()

    assert store.get_node_calls == 0  # everything came from the bulk prefetch
    assert store.existence_calls == 1  # 30 articles, one chunk, one lookup
    assert len(store.edges) == 2 * n - 2  # everyone -> 1 and 2, minus the self loops
