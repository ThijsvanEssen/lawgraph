"""normalize eurlex streams the acts and keeps no article text after writing it."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_ARTICLES
from lawgraph.core.models import Node, PipelineResult
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
        self.batch_sizes: list[int | None] = []

    def query(self, aql: str, bind_vars: dict | None = None, *, batch_size=None):
        self.batch_sizes.append(batch_size)
        return iter([])

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        return node, True

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict[str, Any]]):
        self.docs.setdefault(collection, []).extend(docs)
        return len(docs), 0


def test_the_acts_are_streamed_twenty_at_a_time() -> None:
    store = _Store()
    raw = EurlexNormalizePipeline(store=store).fetch_raw()
    assert not isinstance(raw, list) and list(raw) == []
    assert store.batch_sizes == [
        None,
        20,
    ]  # the count for the progress line, then the acts


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
