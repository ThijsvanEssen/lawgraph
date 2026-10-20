"""make_edge_doc / EdgeWriter: one edge shape, bulk writes only."""

from __future__ import annotations

import pytest

from lawgraph.db import EdgeWriter, edge_key, make_edge_doc
from tests.fakes import FakeStoreBase, InMemoryStore


class _Store(FakeStoreBase):
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []
        self.fail = False

    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        if self.fail:
            raise RuntimeError("boom")
        self.batches.append(list(docs))
        return len(docs), 0


def test_make_edge_doc_shape() -> None:
    doc = make_edge_doc(
        "documents/1",
        "articles/2",
        "REFERS_TO",
        source="s",
        confidence=0.5,
        meta={"mention_count": 1},
    )

    assert doc["key"] == edge_key("documents/1", "REFERS_TO", "articles/2")
    assert (doc["from_id"], doc["to_id"], doc["relation"]) == (
        "documents/1",
        "articles/2",
        "REFERS_TO",
    )
    assert doc["source"] == "s" and doc["status"] == "canoniek"
    assert doc["confidence"] == 0.5 and doc["meta"] == {"mention_count": 1}
    assert doc["created_at"]


def test_make_edge_doc_omits_confidence_when_none() -> None:
    assert "confidence" not in make_edge_doc("documents/1", "articles/2", "REFERS_TO")


def test_make_edge_doc_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        make_edge_doc("documents/1", "articles/2", "REFERS_TO", confidence=1.5)


def test_writer_batches_many_edges_into_few_calls() -> None:
    store = _Store()
    writer = EdgeWriter(store, what=None, batch_size=100)

    for i in range(250):
        writer.add(f"documents/{i}", "articles/1", "REFERS_TO")
    writer.flush()

    assert [len(b) for b in store.batches] == [100, 100, 50]
    assert writer.added == 250 and writer.created == 250


def test_writer_deduplicates_and_skips_missing_ids() -> None:
    store = _Store()
    writer = EdgeWriter(store, what=None)

    assert writer.add(
        "documents/1", "articles/1", "REFERS_TO", meta={"mention_count": 1}
    )
    assert writer.add(
        "documents/1", "articles/1", "REFERS_TO", meta={"mention_count": 2}
    )  # same key: last wins
    assert not writer.add(None, "articles/1", "REFERS_TO")
    assert not writer.add("documents/1", "", "REFERS_TO")
    writer.flush()

    (batch,) = store.batches
    assert len(batch) == 1 and batch[0]["meta"] == {"mention_count": 2}


def test_writer_flush_with_nothing_pending_does_not_call_store() -> None:
    store = _Store()
    assert EdgeWriter(store, what=None).flush() == (0, 0)
    assert store.batches == []


def test_context_manager_flushes_on_success_only() -> None:
    store = _Store()
    with EdgeWriter(store, what=None) as writer:
        writer.add("documents/1", "articles/1", "REFERS_TO")
    assert len(store.batches) == 1

    store2 = _Store()
    with pytest.raises(ValueError):
        with EdgeWriter(store2, what=None) as writer:
            writer.add("documents/1", "articles/1", "REFERS_TO")
            raise ValueError
    assert store2.batches == []


def test_flush_failure_is_raised() -> None:
    store = _Store()
    store.fail = True
    writer = EdgeWriter(store, what=None)
    writer.add("documents/1", "articles/1", "REFERS_TO")
    with pytest.raises(RuntimeError) as raised:
        writer.flush()
    assert "1 edges" in " ".join(raised.value.__notes__)


def test_a_failed_write_keeps_its_batch() -> None:
    """A batch the store did not take stays queued: the next flush writes it."""
    store = _Store()
    store.fail = True
    writer = EdgeWriter(store, what=None, remembers=True)
    writer.add("documents/1", "articles/1", "REFERS_TO")
    with pytest.raises(RuntimeError):
        writer.flush()
    assert writer.written("REFERS_TO") == 1
    store.fail = False
    assert writer.flush() == (1, 0)
    assert [[(d["from_id"], d["to_id"]) for d in batch] for batch in store.batches] == [
        [("documents/1", "articles/1")]
    ]


# ── progress ─────────────────────────────────────────────────────────────────


def test_a_writer_that_names_its_edges_says_how_far_it_is(monkeypatch) -> None:
    """The edge phase of `normalize tk-dossiers` wrote 400,000 edges in minutes of silence:
    the live block of the terminal was empty and the log said nothing."""
    from lawgraph.db import edges as edges_module

    seen: list[tuple[str, str | None]] = []

    def live_status(step: str, line: str | None) -> bool:
        seen.append((step, line))
        return True

    monkeypatch.setattr("lawgraph.core.progress.live_status", live_status)
    writer = edges_module.EdgeWriter(
        InMemoryStore(), what="VOTED edges", batch_size=100
    )
    for number in range(250):
        writer.add(f"members/{number}", "decisions/d", "VOTED", source="test")
    progress = writer.progress
    writer.flush()

    lines = [line for _, line in seen if line]
    assert lines and "VOTED edges" in lines[0]
    assert seen[-1][1] is None  # the line is taken away when the writer is done
    assert progress is not None and progress.done == 250


def test_a_writer_without_a_name_is_silent(monkeypatch) -> None:
    """A semantic pipeline tracks its documents; a second line for their edges would
    take turns with it in the live block."""
    from lawgraph.db import edges as edges_module

    monkeypatch.setattr(
        "lawgraph.core.progress.live_status",
        lambda step, line: (_ for _ in ()).throw(AssertionError("no progress asked")),
    )
    writer = edges_module.EdgeWriter(InMemoryStore(), what=None, batch_size=10)
    for number in range(25):
        writer.add(f"members/{number}", "decisions/d", "VOTED", source="test")
    writer.flush()
    assert writer.created == 25
