"""NodeWriter: buffered, de-duplicated bulk node upserts."""

from __future__ import annotations

import pytest

from lawgraph.core.models import Node, NodeType
from lawgraph.db import NodeWriter


class _Store:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []

    def bulk_insert_or_update_nodes(self, collection: str, docs: list[dict]):
        self.calls.append((collection, list(docs)))
        return len(docs), 0


def _node(key: str, collection: str = "documents", **props) -> Node:
    return Node(
        collection=collection,
        type=NodeType.DOCUMENT,
        key=key,
        props=props,
        _skip_validation=True,
    )


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


def test_node_without_key_is_rejected() -> None:
    node = Node(
        collection="documents",
        type=NodeType.DOCUMENT,
        key=None,
        props={},
        _skip_validation=True,
    )
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
