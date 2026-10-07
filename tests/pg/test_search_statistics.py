"""The statistics of the search: counted on a small table, taken from a sample of the
same pages every time on a large one (``_bm25._stats``)."""

from __future__ import annotations

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries import _bm25


def _instrument(n: int) -> dict[str, object]:
    return {
        "_key": f"i{n}",
        "type": "instrument",
        "labels": [],
        "props": {
            "title": "wet op de " + " ".join(["regel"] * (n % 5 + 1)),
            # a field few have, as the names of a judgment
            **({"aliases": ["WA", "WB", "WC"]} if n % 500 == 0 else {}),
        },
    }


def _fill(store: GraphStore, rows: int) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments", [_instrument(n) for n in range(rows)]
    )
    store.execute("ANALYZE instruments")


def test_a_small_table_is_counted(store: GraphStore) -> None:
    _fill(store, 40)
    stats = _bm25._stats(store, "instruments")
    assert stats["N"] == 40
    assert stats["title/text"] > 1


def test_a_large_table_is_sampled_the_same_every_time(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fill(store, 2000)
    counted = _bm25._stats(store, "instruments")
    monkeypatch.setattr(_bm25, "SAMPLE_ROWS", 100)
    monkeypatch.setattr(_bm25, "MIN_SAMPLED", 10)
    statements: list[str] = []
    query = store.query

    def recording(statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        statements.append(str(statement))
        return query(statement, *args, **kwargs)

    monkeypatch.setattr(store, "query", recording)
    store.bulk_insert_or_update_nodes(
        "instruments", [_instrument(2000)]
    )  # a new version
    sampled = _bm25._stats(store, "instruments")
    store.bulk_insert_or_update_nodes("instruments", [_instrument(2001)])
    again = _bm25._stats(store, "instruments")

    assert any("TABLESAMPLE SYSTEM" in s for s in statements)
    assert sampled["N"] == pytest.approx(2000, rel=0.05)  # the planner's count
    assert sampled["title/text"] == pytest.approx(counted["title/text"], rel=0.25)
    # too rare for the sample: measured over the whole table
    assert counted["aliases/identity"] == 3
    assert sampled["aliases/identity"] == 3
    assert again["N"] == pytest.approx(sampled["N"], rel=0.01)
    assert again["title/text"] == pytest.approx(sampled["title/text"], rel=0.05)
