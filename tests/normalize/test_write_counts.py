"""What a normalize pipeline writes ends up as created/updated on its result."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import CountingStore, EdgeWriter, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase
from lawgraph.pipelines.normalize.echr import ECHRNormalizePipeline
from tests.conftest import _BaseFakeStore
from tests.fakes import RawSourcesFake


def _node(key: str, collection: str = "documents") -> Node:
    return Node(
        collection=collection,
        type=NodeType.DOCUMENT,
        key=key,
        props={},
        _skip_validation=True,
    )


def _link_in_helper(store: Any, from_id: str, to_id: str) -> None:
    """Like the tk_* helper modules: gets the store, builds its own writer."""
    with EdgeWriter(store, what=None) as writer:
        writer.add(from_id, to_id, "PART_OF", source="test")


class _Pipeline(NormalizePipelineBase):
    """Writes through every path the real pipelines use."""

    def __init__(self, store: Any, *, fail_in_edges: bool = False) -> None:
        super().__init__(store)
        self._fail_in_edges = fail_in_edges

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[str]:
        return ["a", "b", "c"]

    def normalize_nodes(self, raw: list[str], result: PipelineResult) -> list[Node]:
        nodes = [_node(key) for key in raw]
        with NodeWriter(self.store) as writer:
            writer.add_all(nodes)
        self.store.insert_or_update(_node("law", "instruments"))
        self.store.bulk_insert_or_update_nodes(
            "documents", [_node("direct").to_document()]
        )
        result.skipped += 1
        return nodes

    def build_edges(self, raw: list[str], normalized: list[Node]) -> None:
        if self._fail_in_edges:
            raise RuntimeError("boom")
        for node in normalized:
            _link_in_helper(self.store, node.arango_id, "instruments/law")


# ── CountingStore ────────────────────────────────────────────────────────────


def test_counting_store_separates_created_from_updated_for_nodes_and_edges() -> None:
    store = CountingStore(_BaseFakeStore())
    docs = [_node("a").to_document(), _node("b").to_document()]
    edge = {"_key": "e1", "_from": "documents/a", "_to": "documents/b"}

    store.bulk_insert_or_update_nodes("documents", docs[:1])
    store.bulk_insert_or_update_nodes("documents", docs)
    store.insert_or_update(_node("b"))
    store.bulk_insert_or_update_edges([edge])
    store.bulk_insert_or_update_edges([edge])

    writes = store.writes
    assert (writes.nodes_created, writes.nodes_updated) == (2, 2)
    assert (writes.edges_created, writes.edges_updated) == (1, 1)
    assert (writes.created, writes.updated) == (3, 3)


def test_counting_store_returns_what_the_store_returns() -> None:
    inner = _BaseFakeStore()
    store = CountingStore(inner)

    assert store.bulk_insert_or_update_nodes(
        "documents", [_node("a").to_document()]
    ) == (1, 0)
    stored, created = store.insert_or_update(_node("a"))
    assert (stored.key, created) == ("a", False)
    assert store.edges is inner.edges  # everything else passes through


def test_reset_counts_starts_a_fresh_tally() -> None:
    store = CountingStore(_BaseFakeStore())
    store.bulk_insert_or_update_nodes("documents", [_node("a").to_document()])

    store.reset_counts()

    assert (store.writes.created, store.writes.updated) == (0, 0)


# ── NormalizePipelineBase.run ────────────────────────────────────────────────


def test_run_reports_every_write_path_without_the_pipeline_counting() -> None:
    result = _Pipeline(_BaseFakeStore()).run()

    # 3 via NodeWriter + 1 single upsert + 1 direct bulk call + 3 helper edges
    assert (result.created, result.updated, result.skipped) == (8, 0, 1)
    assert result.summary() == "8 created, 1 skipped"


def test_second_run_over_the_same_data_reports_updates_not_creations() -> None:
    store = _BaseFakeStore()
    _Pipeline(store).run()

    result = _Pipeline(store).run()

    assert (result.created, result.updated) == (0, 8)


def test_rerunning_one_pipeline_instance_does_not_carry_counts_over() -> None:
    pipeline = _Pipeline(_BaseFakeStore())
    pipeline.run()

    result = pipeline.run()

    assert (result.created, result.updated) == (0, 8)


def test_a_run_that_raises_says_what_it_wrote_before_and_lets_the_error_out(
    caplog,
) -> None:
    """``run_command`` names the step and the error; the pipeline does not half-handle it."""
    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="boom"):
        _Pipeline(_BaseFakeStore(), fail_in_edges=True).run()
    assert any(
        "Written before the failure: nodes 5 created" in message
        for message in caplog.messages
    )


# ── a real pipeline, end to end ──────────────────────────────────────────────


class _RawSourceStore(RawSourcesFake, _BaseFakeStore):
    def __init__(self, raw: list[dict[str, Any]]) -> None:
        super().__init__()
        self._raw = raw

    def query(self, aql: str, bind_vars: dict | None = None, **_kw: Any) -> list[dict]:
        return self._raw


def test_echr_pipeline_summary_tells_new_judgments_from_known_ones() -> None:
    def record(item_id: str) -> dict[str, Any]:
        return {"external_id": item_id, "payload_json": {"itemid": item_id}}

    store = _RawSourceStore([record("001-1")])
    first = ECHRNormalizePipeline(store=store).run()
    store._raw.append(record("001-2"))
    second = ECHRNormalizePipeline(store=store).run()

    assert first.summary() == "1 created"
    assert second.summary() == "1 created, 1 updated"
