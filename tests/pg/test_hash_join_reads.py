"""The reads that hung a full build keep ``hash_joins``: each joins a set the planner takes
for a row or two (a condition on JSON, a list of keys) where there are 10^5, and a nested
loop over it ran for hours. The other tests here check what they return; this checks that
they still ask the store for hash joins."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries import _chunks, government
from lawgraph.db.queries.normalize import tk
from lawgraph.db.queries.semantic import bwb


def _recorded(store: GraphStore, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The ``hash_joins`` of every read *store* runs from now on."""
    calls: list[Any] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        calls.append(options.get("hash_joins"))
        return query(statement, params, **options)

    monkeypatch.setattr(store, "query", recording)
    return calls


@pytest.mark.parametrize(
    "read",
    [
        government.dossier_first_signatures,
        tk.government_signatures,
        tk.government_signatures_by_month,
        lambda store: _chunks.delete_keys(
            store, "edges", "SELECT key FROM edges WHERE false", {}
        ),
    ],
)
def test_the_read_asks_for_hash_joins(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch, read: Any
) -> None:
    calls = _recorded(store, monkeypatch)
    result = read(store)
    if not isinstance(result, int):
        list(result)
    assert calls == [True]


def test_the_title_matches_ask_for_hash_joins(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _recorded(store, monkeypatch)
    bwb.staatsblad_instrument_matches(store)
    bwb.staatscourant_instrument_matches(store, None)
    # by BWB id (an index lookup per publication), then by title (hash joins)
    assert calls == [None, True, None, True]
