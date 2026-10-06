"""The reads that hung a full build keep ``hash_joins``: each joins a set the planner takes
for a row or two (a condition on JSON, a list of keys) where there are 10^5, and a nested
loop over it ran for hours. ``tests/pg`` checks what they return; this checks that they
still ask the store for hash joins."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db.queries import _chunks, government
from lawgraph.db.queries.normalize import tk
from lawgraph.db.queries.semantic import bwb


class _Recording:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query(self, statement: Any, params: Any = None, **options: Any) -> Any:
        self.calls.append(options)
        return iter([])

    def execute(self, statement: Any, params: Any = None) -> list[Any]:
        return []


@pytest.mark.parametrize(
    "read",
    [
        government.dossier_first_signatures,
        tk.government_signatures,
        tk.government_signatures_by_month,
        lambda store: _chunks.delete_keys(store, "edges", "SELECT key FROM edges", {}),
    ],
)
def test_the_read_asks_for_hash_joins(read: Any) -> None:
    store = _Recording()
    list(read(store) or [])
    assert [call.get("hash_joins") for call in store.calls] == [True]


def test_the_title_matches_ask_for_hash_joins() -> None:
    store = _Recording()
    bwb.staatsblad_instrument_matches(store)
    bwb.staatscourant_instrument_matches(store, None)
    # by BWB id (an index lookup per publication), then by title (hash joins)
    assert [call.get("hash_joins") for call in store.calls] == [None, True, None, True]
