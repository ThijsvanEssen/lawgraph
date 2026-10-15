"""``/api/stats`` ``lists``: one entry per list of the explorer's index, each counted by
its own route and kept per the tables it reads."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.api import list_totals as module
from lawgraph.api.list_totals import LISTS, ListTotal, list_totals

# The lists of the explorer's index (``INDEX_GROUPS`` in
# ``lawgraph-explorer/src/lib/components/explore/index/categories.ts``); its
# ``ministers`` are ``bewindspersonen`` here.
EXPLORER_LISTS = {
    "instruments",
    "judgments",
    "dossiers",
    "decisions",
    "documents",
    "members",
    "factions",
    "committees",
    "cabinets",
    "bewindspersonen",
    "commitments",
}


def test_the_lists_are_those_of_the_explorer() -> None:
    assert set(LISTS) == EXPLORER_LISTS


def test_each_list_is_counted_once_and_kept_per_its_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kept: dict[Any, Any] = {}

    def cached(store: Any, key: Any, compute: Any, *, tables: Any) -> Any:
        kept[key] = tables
        return compute()

    monkeypatch.setattr(module, "cached", cached)
    for name, entry in list(LISTS.items()):
        counted = ListTotal(entry.tables, lambda store, name=name: len(name))
        monkeypatch.setitem(LISTS, name, counted)
    totals = list_totals(None)  # type: ignore[arg-type]
    assert totals == {name: len(name) for name in LISTS}
    assert kept == {
        ("stats list", name): entry.tables
        for name, entry in LISTS.items()
        if entry.tables
    }
