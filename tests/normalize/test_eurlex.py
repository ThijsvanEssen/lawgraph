"""normalize eurlex streams the acts and keeps no article text after writing it."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    RAW_KIND_EU_CELEX,
    SOURCE_EURLEX,
)
from lawgraph.core.models import Node, PipelineResult
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.eurlex import EurlexNormalizePipeline
from tests.fakes import RawSourcesFake

HTML = (
    "<html><body><p>Artikel 1</p><p>Deze richtlijn stelt regels vast voor de vertolking.</p>"
    "<p>Artikel 2</p><p>De lidstaten zorgen ervoor dat verdachten een tolk krijgen.</p>"
    "</body></html>"
)


class _Store(RawSourcesFake):
    def __init__(self) -> None:
        self.docs: dict[str, list[dict[str, Any]]] = {}

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        return node, True

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict[str, Any]]):
        self.docs.setdefault(collection, []).extend(docs)
        return len(docs), 0


def test_the_acts_are_streamed_twenty_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, dict[str, Any]]] = []

    def count_raw_records(store: Any, source: str, kinds: list[str]) -> int:
        asked.append(("count", {"source": source, "kinds": kinds}))
        return 0

    def iter_raw_records(store: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        asked.append(("records", kwargs))
        return iter([])

    monkeypatch.setattr(raw_queries, "count_raw_records", count_raw_records)
    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)

    raw = EurlexNormalizePipeline(store=_Store()).fetch_raw()
    assert not isinstance(raw, list) and list(raw) == []
    acts = {"source": SOURCE_EURLEX, "kinds": [RAW_KIND_EU_CELEX]}
    # the count for the progress line, then the acts
    assert asked == [
        ("count", acts),
        (
            "records",
            {**acts, "since_iso": None, "batch_size": 20, "chronological": False},
        ),
    ]


def test_the_article_text_is_written_and_not_kept() -> None:
    store = _Store()
    records = iter(  # a generator: walked once
        [{"payload_text": HTML, "meta": {"celex": "32010L0064", "lang": "NL"}}]
    )
    normalized = EurlexNormalizePipeline(store=store).normalize_nodes(
        records, PipelineResult()
    )

    written = {d["_key"]: d["props"]["text"] for d in store.docs[COLLECTION_ARTICLES]}
    kept = normalized["articles_by_celex"]["32010L0064"]
    assert len(written) == len(kept) == 2 and all(written.values())
    assert [node.props for node in kept] == [{}, {}]
    assert {node.key for node in kept} == set(written)
