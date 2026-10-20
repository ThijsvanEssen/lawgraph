"""EdgeWriter remembers what it wrote: ``remove_stale`` removes what a run no longer derives.

The removal queries are pg (``tests/pg``); here they are replaced by recorders, so what is
checked is which keys the writer hands them as written.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import EdgeWriter, edge_key
from lawgraph.db.queries import removals
from tests.fakes import FakeStoreBase


class _Store(FakeStoreBase):
    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        return len(docs), 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
    seen: list[tuple[str, tuple[Any, ...]]] = []

    def record_at(
        _store: Any, *args: Any, source: str, other_ends: Any = None
    ) -> list[tuple[str, str]]:
        seen.append(("remove_edges_at", (*args, source)))
        return [("documents/x", "articles/x")]

    def record_except(_store: Any, *args: Any, source: str | None) -> int:
        seen.append(("remove_edges_except", (*args, source)))
        return 1

    monkeypatch.setattr(removals, "remove_edges_at", record_at)
    monkeypatch.setattr(removals, "remove_edges_except", record_except)
    return seen


def _writer() -> EdgeWriter:
    writer = EdgeWriter(_Store(), what=None, remembers=True)
    writer.add("documents/1", "articles/1", "REFERS_TO", source="s")
    writer.add("documents/1", "articles/2", "REFERS_TO", source="s")
    writer.add("documents/2", "articles/1", "REFERS_TO", source="s")
    writer.add("documents/1", "articles/1", "AMENDS", source="s")
    assert not writer.add(
        "documents/3", None, "REFERS_TO", source="s"
    )  # not written: not kept
    writer.flush()
    return writer


def test_remove_stale_keeps_the_keys_written_from_each_node(calls) -> None:
    assert (
        _writer().remove_stale(
            "REFERS_TO", "s", ["documents/1", "documents/2", "documents/3"]
        )
        == 1
    )

    ((name, (end, relations, from_ids, keep, source)),) = calls
    assert (name, end, relations, source, from_ids) == (
        "remove_edges_at",
        "from_id",
        ["REFERS_TO"],
        "s",
        ["documents/1", "documents/2", "documents/3"],
    )
    assert keep == {
        "documents/1": {
            edge_key("documents/1", "REFERS_TO", "articles/1"),
            edge_key("documents/1", "REFERS_TO", "articles/2"),
        },
        "documents/2": {edge_key("documents/2", "REFERS_TO", "articles/1")},
    }


def test_removed_stale_hands_the_same_keys_on(calls) -> None:
    assert _writer().removed_stale("REFERS_TO", "s", ["documents/2"]) == [
        ("documents/x", "articles/x")
    ]

    ((name, (end, _, from_ids, keep, _)),) = calls
    assert (name, end, from_ids, keep["documents/2"]) == (
        "remove_edges_at",
        "from_id",
        ["documents/2"],
        {edge_key("documents/2", "REFERS_TO", "articles/1")},
    )


def test_remove_stale_to_keeps_the_keys_written_into_each_node(calls) -> None:
    assert _writer().remove_stale_to(["REFERS_TO", "AMENDS"], "s", ["articles/1"]) == 1

    ((name, (end, relations, to_ids, keep, source)),) = calls
    assert (name, end, relations, source, to_ids) == (
        "remove_edges_at",
        "to_id",
        ["REFERS_TO", "AMENDS"],
        "s",
        ["articles/1"],
    )
    assert keep == {
        "articles/1": {
            edge_key("documents/1", "REFERS_TO", "articles/1"),
            edge_key("documents/2", "REFERS_TO", "articles/1"),
            edge_key("documents/1", "AMENDS", "articles/1"),
        },
    }


def test_edges_written_after_a_removal_by_end_are_kept_by_the_next(calls) -> None:
    """A step that removes per chunk (bwb-amendments) asks again after writing more."""
    writer = _writer()
    writer.remove_stale_to(["REFERS_TO"], "s", ["articles/1"])
    writer.add("documents/9", "articles/9", "REFERS_TO", source="s")
    writer.remove_stale_to(["REFERS_TO"], "s", ["articles/9"])

    assert calls[-1][1][3] == {
        "articles/9": {edge_key("documents/9", "REFERS_TO", "articles/9")}
    }


def test_remove_stale_of_source_keeps_every_key_of_the_relation(calls) -> None:
    writer = _writer()
    writer.remove_stale_of_source("REFERS_TO", "s")
    writer.remove_stale_of_source("AMENDS", None)  # every source

    (name, (relation, keep, source)), (other, (other_relation, other_keep, none)) = (
        calls
    )
    assert (name, relation, source, none) == (
        "remove_edges_except",
        "REFERS_TO",
        "s",
        None,
    )
    assert sorted(keep) == sorted(
        edge_key(f, "REFERS_TO", t)
        for f, t in (
            ("documents/1", "articles/1"),
            ("documents/1", "articles/2"),
            ("documents/2", "articles/1"),
        )
    )
    assert (other, other_relation, other_keep) == (
        "remove_edges_except",
        "AMENDS",
        [edge_key("documents/1", "AMENDS", "articles/1")],
    )


def test_a_relation_never_written_keeps_nothing(calls) -> None:
    _writer().remove_stale("NEVER", "s", ["documents/1"])
    assert calls[0][1][3] == {}


def test_written_counts_each_edge_once_and_survives_the_flush() -> None:
    writer = EdgeWriter(_Store(), what=None, remembers=True, batch_size=2)
    for _ in range(2):
        for to in ("articles/1", "articles/2", "articles/3"):
            writer.add("documents/1", to, "REFERS_TO")
    writer.flush()
    assert writer.written("REFERS_TO") == 3 and writer.written("AMENDS") == 0


def test_a_writer_that_does_not_remember_cannot_remove() -> None:
    writer = EdgeWriter(_Store(), what=None)
    writer.add("documents/1", "articles/1", "REFERS_TO")
    with pytest.raises(RuntimeError):
        writer.remove_stale("REFERS_TO", "s", ["documents/1"])
