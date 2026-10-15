"""EdgeWriter remembers what it wrote: ``remove_stale`` removes what a run no longer derives.

The removal queries are pg (``tests/pg``); here they are replaced by recorders, so what is
checked is which keys the writer hands them as written.
"""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import EdgeWriter, edge_key
from lawgraph.db.queries import removals


class _Store:
    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        return len(docs), 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
    seen: list[tuple[str, tuple[Any, ...]]] = []

    def record_at(_store: Any, *args: Any, source: str) -> list[tuple[str, str]]:
        seen.append(("remove_edges_at", (*args, source)))
        return [("a/x", "b/x")]

    def record_except(_store: Any, *args: Any, source: str | None) -> int:
        seen.append(("remove_edges_except", (*args, source)))
        return 1

    monkeypatch.setattr(removals, "remove_edges_at", record_at)
    monkeypatch.setattr(removals, "remove_edges_except", record_except)
    return seen


def _writer() -> EdgeWriter:
    writer = EdgeWriter(_Store(), what=None, remembers=True)
    writer.add("a/1", "b/1", "REL", source="s")
    writer.add("a/1", "b/2", "REL", source="s")
    writer.add("a/2", "b/1", "REL", source="s")
    writer.add("a/1", "b/1", "OTHER", source="s")
    assert not writer.add("a/3", None, "REL", source="s")  # not written: not kept
    writer.flush()
    return writer


def test_remove_stale_keeps_the_keys_written_from_each_node(calls) -> None:
    assert _writer().remove_stale("REL", "s", ["a/1", "a/2", "a/3"]) == 1

    ((name, (end, relations, from_ids, keep, source)),) = calls
    assert (name, end, relations, source, from_ids) == (
        "remove_edges_at",
        "from_id",
        ["REL"],
        "s",
        ["a/1", "a/2", "a/3"],
    )
    assert keep == {
        "a/1": {edge_key("a/1", "REL", "b/1"), edge_key("a/1", "REL", "b/2")},
        "a/2": {edge_key("a/2", "REL", "b/1")},
    }


def test_removed_stale_hands_the_same_keys_on(calls) -> None:
    assert _writer().removed_stale("REL", "s", ["a/2"]) == [("a/x", "b/x")]

    ((name, (end, _, from_ids, keep, _)),) = calls
    assert (name, end, from_ids, keep["a/2"]) == (
        "remove_edges_at",
        "from_id",
        ["a/2"],
        {edge_key("a/2", "REL", "b/1")},
    )


def test_remove_stale_to_keeps_the_keys_written_into_each_node(calls) -> None:
    assert _writer().remove_stale_to(["REL", "OTHER"], "s", ["b/1"]) == 1

    ((name, (end, relations, to_ids, keep, source)),) = calls
    assert (name, end, relations, source, to_ids) == (
        "remove_edges_at",
        "to_id",
        ["REL", "OTHER"],
        "s",
        ["b/1"],
    )
    assert keep == {
        "b/1": {
            edge_key("a/1", "REL", "b/1"),
            edge_key("a/2", "REL", "b/1"),
            edge_key("a/1", "OTHER", "b/1"),
        },
    }


def test_edges_written_after_a_removal_by_end_are_kept_by_the_next(calls) -> None:
    """A step that removes per chunk (bwb-amendments) asks again after writing more."""
    writer = _writer()
    writer.remove_stale_to(["REL"], "s", ["b/1"])
    writer.add("a/9", "b/9", "REL", source="s")
    writer.remove_stale_to(["REL"], "s", ["b/9"])

    assert calls[-1][1][3] == {"b/9": {edge_key("a/9", "REL", "b/9")}}


def test_remove_stale_of_source_keeps_every_key_of_the_relation(calls) -> None:
    writer = _writer()
    writer.remove_stale_of_source("REL", "s")
    writer.remove_stale_of_source("OTHER", None)  # every source

    (name, (relation, keep, source)), (other, (other_relation, other_keep, none)) = (
        calls
    )
    assert (name, relation, source, none) == ("remove_edges_except", "REL", "s", None)
    assert sorted(keep) == sorted(
        edge_key(f, "REL", t)
        for f, t in (("a/1", "b/1"), ("a/1", "b/2"), ("a/2", "b/1"))
    )
    assert (other, other_relation, other_keep) == (
        "remove_edges_except",
        "OTHER",
        [edge_key("a/1", "OTHER", "b/1")],
    )


def test_a_relation_never_written_keeps_nothing(calls) -> None:
    _writer().remove_stale("NEVER", "s", ["a/1"])
    assert calls[0][1][3] == {}


def test_written_counts_each_edge_once_and_survives_the_flush() -> None:
    writer = EdgeWriter(_Store(), what=None, remembers=True, batch_size=2)
    for _ in range(2):
        for to in ("b/1", "b/2", "b/3"):
            writer.add("a/1", to, "REL")
    writer.flush()
    assert writer.written("REL") == 3 and writer.written("OTHER") == 0


def test_a_writer_that_does_not_remember_cannot_remove() -> None:
    writer = EdgeWriter(_Store(), what=None)
    writer.add("a/1", "b/1", "REL")
    with pytest.raises(RuntimeError):
        writer.remove_stale("REL", "s", ["a/1"])
