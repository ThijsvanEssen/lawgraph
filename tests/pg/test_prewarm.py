"""What the search reads, read into memory on a real PostgreSQL (``lawgraph prewarm``)."""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.db.queries.search import prewarm


def _article(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "key": "a1",
                "type": "article",
                "labels": [],
                "props": {"display_name": "Artikel 1", "text": "onrechtmatige daad"},
            }
        ],
    )


def test_the_search_indexes_go_to_the_buffers_and_the_heaps_to_the_cache(
    store: GraphStore,
) -> None:
    _article(store)
    warmed = prewarm.prewarm(store)
    modes = {w.relation: w.mode for w in warmed}
    assert modes["articles_s_text_t"] == "buffer"
    assert modes["dossiers_s_title_t"] == "buffer"
    assert modes["judgments_s_summary_t"] == "buffer"
    assert modes["articles"] == "read"
    assert any(r.startswith("pg_toast.") and m == "read" for r, m in modes.items())
    assert not any(w.skipped for w in warmed)
    blocks = {w.relation: w.blocks for w in warmed}
    assert blocks["articles"] > 0 and blocks["articles_s_text_t"] > 0


def test_a_relation_that_does_not_fit_is_skipped_and_the_next_still_read(
    store: GraphStore,
) -> None:
    _article(store)
    warmed = prewarm.prewarm(store, heap_mb=0)
    heaps = [w for w in warmed if w.mode == "read"]
    assert [w.relation for w in heaps if w.skipped] == [
        "articles"
    ]  # an empty TOAST fits
    assert all(not w.skipped for w in warmed if w.mode == "buffer")
