"""Tests for the explanatory-memorandum (MvT/NvT) semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_EXPLAINS
from lawgraph.core.relations import BY_NAME
from lawgraph.pipelines.semantic.mvt_articles import MvtArticlesSemanticPipeline
from tests.conftest import _BaseFakeStore


class _FakeStore(_BaseFakeStore):
    """Returns the rows the single targets query would produce."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self._rows = rows
        self.queries: list[str] = []

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        self.queries.append(aql)
        return list(self._rows)


def test_pipeline_explains_the_article_versions_the_instrument_changed() -> None:
    store = _FakeStore(
        [
            {
                "document": "documents/mvt-1",
                "targets": [
                    "article_versions/bwbr0001854_stam1_v2",
                    "articles/bwbr0001854_91",
                ],
            }
        ]
    )

    result = MvtArticlesSemanticPipeline(store=store).run()

    assert result.created == 2
    spec = BY_NAME[RELATION_EXPLAINS]
    for edge in store.edges.values():
        assert edge["relation"] == RELATION_EXPLAINS
        assert edge["_from"].split("/")[0] in spec.sources
        assert edge["_to"].split("/")[0] in spec.targets


def test_pipeline_falls_back_to_the_instrument() -> None:
    store = _FakeStore(
        [{"document": "documents/nvt-1", "targets": ["instruments/bwbr0009999"]}]
    )

    result = MvtArticlesSemanticPipeline(store=store).run()

    assert result.created == 1
    (edge,) = store.edges.values()
    assert edge["_to"] == "instruments/bwbr0009999"


def test_pipeline_reads_the_graph_in_a_single_pass() -> None:
    store = _FakeStore(
        [
            {"document": f"documents/mvt-{n}", "targets": [f"articles/a{n}"]}
            for n in range(50)
        ]
    )

    result = MvtArticlesSemanticPipeline(store=store).run()

    assert result.created == 50
    assert len(store.queries) == 1


def test_pipeline_returns_empty_when_no_documents() -> None:
    store = _FakeStore([])

    result = MvtArticlesSemanticPipeline(store=store).run()

    assert result.created == 0
    assert not store.edges


def test_pipeline_skips_rows_without_targets() -> None:
    store = _FakeStore([{"document": "documents/mvt-1", "targets": []}])

    result = MvtArticlesSemanticPipeline(store=store).run()

    assert (result.created, result.skipped) == (0, 1)
