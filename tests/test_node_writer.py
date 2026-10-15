"""NodeWriter: buffered, de-duplicated bulk node upserts."""

from __future__ import annotations

import pytest

from lawgraph.core.models import Node
from lawgraph.db import NodeWriter
from tests.fakes import FakeStoreBase


class _Store(FakeStoreBase):
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []
        self.fail = False

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict]):
        if self.fail:
            raise RuntimeError("refused")
        self.calls.append((collection, list(docs)))
        return len(docs), 0


def _node(key: str, collection: str = "documents", **props) -> Node:
    return Node.skeleton(collection, key, props)


def test_batches_nodes_and_flushes_the_rest() -> None:
    store = _Store()
    writer = NodeWriter(store, batch_size=100)

    for i in range(250):
        writer.add(_node(f"n{i}"))
    writer.flush()

    assert [len(docs) for _, docs in store.calls] == [100, 100, 50]
    assert writer.written == 250


def test_groups_by_collection_and_deduplicates_by_key() -> None:
    store = _Store()
    writer = NodeWriter(store)

    writer.add(_node("a", v=1))
    writer.add(_node("a", v=2))  # same key: last wins
    writer.add(_node("b", collection="judgments"))
    writer.flush()

    by_collection = dict(store.calls)
    assert [d["props"] for d in by_collection["documents"]] == [{"v": 2}]
    assert len(by_collection["judgments"]) == 1


def test_two_nodes_with_one_key_in_a_batch_merge_as_the_store_does() -> None:
    store = _Store()
    writer = NodeWriter(store)

    first = _node("a", title="Verdrag", status="Inwerkinggetreden")
    first.labels = ["Verdrag"]
    second = _node("a", status=None, parties=[{"name": "België"}])
    second.labels = ["Verdrag", "NL"]
    writer.add(first)
    writer.add(second)
    writer.flush()

    [(_, [doc])] = store.calls
    assert doc["props"] == {
        "title": "Verdrag",
        "status": None,
        "parties": [{"name": "België"}],
    }
    assert doc["labels"] == ["Verdrag", "NL"]
    assert writer.written == 1


def test_node_without_key_is_rejected() -> None:
    node = Node.skeleton("documents", None)
    with pytest.raises(ValueError):
        NodeWriter(_Store()).add(node)


def test_context_manager_flushes_only_on_success() -> None:
    store = _Store()
    with NodeWriter(store) as writer:
        writer.add(_node("a"))
    assert len(store.calls) == 1

    failed = _Store()
    with pytest.raises(RuntimeError):
        with NodeWriter(failed) as writer:
            writer.add(_node("a"))
            raise RuntimeError
    assert failed.calls == []


def test_a_failed_write_raises_with_its_batch_and_keeps_it() -> None:
    store = _Store()
    store.fail = True
    writer = NodeWriter(store)
    writer.add(_node("a"))
    with pytest.raises(RuntimeError) as raised:
        writer.flush()
    assert raised.value.__notes__ == [
        "Writing a batch of 1 documents failed; it stays queued."
    ]
    store.fail = False
    assert writer.flush() == 1
    assert [doc["key"] for _, docs in store.calls for doc in docs] == ["a"]


def test_a_batch_of_large_nodes_is_written_by_size() -> None:
    """500 judgments with their XML and text are hundreds of MB in one query."""
    from lawgraph.db import nodes as nodes_module

    store = _Store()
    writer = NodeWriter(store)
    big = "x" * (nodes_module.MAX_BATCH_BYTES // 4)
    for number in range(9):
        writer.add(Node.skeleton("judgments", f"j{number}", {"text": big}))
    writer.flush()
    assert [len(docs) for _, docs in store.calls] == [4, 4, 1]
