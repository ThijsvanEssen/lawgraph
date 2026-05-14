"""Tests for the VersionCausesSemanticPipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.semantic.version_causes import VersionCausesSemanticPipeline


class _FakeStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.created_edges: list[dict[str, Any]] = []

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        return list(self._rows)

    def create_edge(
        self,
        from_id: str,
        to_id: str,
        relation: str,
        source: str,
        **kwargs: Any,
    ) -> None:
        self.created_edges.append(
            {"from_id": from_id, "to_id": to_id, "relation": relation}
        )


def test_pipeline_creates_caused_version_edges() -> None:
    rows = [
        {
            "av_id": "instrument_article_versions/v1",
            "pub_id": "publications/pub1",
            "datum": "2022-01-01",
        },
        {
            "av_id": "instrument_article_versions/v2",
            "pub_id": "publications/pub2",
            "datum": "2022-06-15",
        },
    ]
    store = _FakeStore(rows=rows)
    pipeline = VersionCausesSemanticPipeline(store=store)
    result = pipeline.run()

    assert result.created == 2
    assert len(store.created_edges) == 2
    relations = {e["relation"] for e in store.created_edges}
    assert "CAUSED_VERSION" in relations


def test_pipeline_returns_zero_when_no_rows() -> None:
    store = _FakeStore(rows=[])
    pipeline = VersionCausesSemanticPipeline(store=store)
    result = pipeline.run()
    assert result.created == 0
    assert len(store.created_edges) == 0
