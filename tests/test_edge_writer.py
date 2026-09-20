"""make_edge_doc / EdgeWriter: one edge shape, bulk writes only."""

from __future__ import annotations

import pytest

from lawgraph.db import EdgeWriter, edge_key, make_edge_doc


class _Store:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []
        self.fail = False

    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        if self.fail:
            raise RuntimeError("boom")
        self.batches.append(list(docs))
        return len(docs), 0


def test_make_edge_doc_shape() -> None:
    doc = make_edge_doc("a/1", "b/2", "REL", source="s", confidence=0.5, meta={"k": 1})

    assert doc["_key"] == edge_key("a/1", "REL", "b/2")
    assert (doc["_from"], doc["_to"], doc["relation"]) == ("a/1", "b/2", "REL")
    assert doc["source"] == "s" and doc["status"] == "canoniek"
    assert doc["confidence"] == 0.5 and doc["meta"] == {"k": 1}
    assert doc["created_at"]


def test_make_edge_doc_omits_confidence_when_none() -> None:
    assert "confidence" not in make_edge_doc("a/1", "b/2", "REL")


def test_make_edge_doc_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        make_edge_doc("a/1", "b/2", "REL", confidence=1.5)


def test_writer_batches_many_edges_into_few_calls() -> None:
    store = _Store()
    writer = EdgeWriter(store, batch_size=100)

    for i in range(250):
        writer.add(f"a/{i}", "b/1", "REL")
    writer.flush()

    assert [len(b) for b in store.batches] == [100, 100, 50]
    assert writer.added == 250 and writer.created == 250


def test_writer_deduplicates_and_skips_missing_ids() -> None:
    store = _Store()
    writer = EdgeWriter(store)

    assert writer.add("a/1", "b/1", "REL", meta={"v": 1})
    assert writer.add("a/1", "b/1", "REL", meta={"v": 2})  # same key: last wins
    assert not writer.add(None, "b/1", "REL")
    assert not writer.add("a/1", "", "REL")
    writer.flush()

    (batch,) = store.batches
    assert len(batch) == 1 and batch[0]["meta"] == {"v": 2}


def test_writer_flush_with_nothing_pending_does_not_call_store() -> None:
    store = _Store()
    assert EdgeWriter(store).flush() == (0, 0)
    assert store.batches == []


def test_context_manager_flushes_on_success_only() -> None:
    store = _Store()
    with EdgeWriter(store) as writer:
        writer.add("a/1", "b/1", "REL")
    assert len(store.batches) == 1

    store2 = _Store()
    with pytest.raises(ValueError):
        with EdgeWriter(store2) as writer:
            writer.add("a/1", "b/1", "REL")
            raise ValueError
    assert store2.batches == []


def test_flush_failure_is_raised() -> None:
    store = _Store()
    store.fail = True
    writer = EdgeWriter(store)
    writer.add("a/1", "b/1", "REL")
    with pytest.raises(RuntimeError):
        writer.flush()
