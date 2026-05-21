"""Tests for the MvT/NvT artikel-toelichting semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.pipelines.semantic.mvt_articles import MvtArticleSemanticPipeline


class _FakeStore:
    def __init__(
        self,
        *,
        pub_rows: list[dict[str, Any]],
        article_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self._pub_rows = pub_rows
        self._article_rows = article_rows or []
        self.edges: dict[str, dict[str, Any]] = {}

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        if "instrument_articles" in aql:
            return list(self._article_rows)
        return list(self._pub_rows)

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created


def _make_article_row(key: str, bwb_id: str, number: str) -> dict[str, Any]:
    return {
        "number": number,
        "id": f"instrument_articles/{key}",
        "key": key,
    }


def test_pipeline_creates_licht_toe_edge() -> None:
    bwb_id = "BWBR0001854"
    article_key = "bwbr0001854_91"

    pub_rows = [
        {
            "pub_id": "publications/mvt-1",
            "pub_key": "mvt-1",
            "text": (
                "Artikelsgewijze toelichting\n"
                "Artikel 91\nDit artikel regelt de algemene bepalingen."
            ),
            "instruments": [
                {"id": "instruments/bwbr0001854", "bwb_id": bwb_id, "celex": None}
            ],
        }
    ]
    article_rows = [_make_article_row(article_key, bwb_id, "91")]

    store = _FakeStore(pub_rows=pub_rows, article_rows=article_rows)
    pipeline = MvtArticleSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()

    assert result.created == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == "LICHT_TOE"
    assert edge["_from"].startswith("publications/")
    assert edge["_to"].startswith("instrument_articles/")


def test_pipeline_returns_empty_when_no_publications() -> None:
    store = _FakeStore(pub_rows=[])
    pipeline = MvtArticleSemanticPipeline(store=store, domain_config={})
    result = pipeline.run()
    assert result.created == 0
    assert len(store.edges) == 0
