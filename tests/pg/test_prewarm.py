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


def test_the_search_indexes_are_read_then_the_heaps_asked_for(
    store: GraphStore,
) -> None:
    _article(store)
    assert "articles" not in prewarm.relations(store)  # no heap by default
    warmed = prewarm.prewarm(store, heaps=("articles",))
    order = [w.relation for w in warmed]
    assert {"articles_s_text_t", "dossiers_s_title_t", "judgments_s_summary_t"} <= set(
        order
    )
    assert order.index("judgments_s_summary_t") < order.index("articles")
    assert order[-1].startswith("pg_toast.")  # the TOAST of the articles
    assert [w.relation for w in warmed if w.skipped] == []
    blocks = {w.relation: w.blocks for w in warmed}
    assert blocks["articles"] > 0 and blocks["articles_s_text_t"] > 0


def test_a_relation_that_does_not_fit_is_skipped_and_the_next_still_read(
    store: GraphStore,
) -> None:
    _article(store)
    warmed = prewarm.prewarm(store, heaps=("articles",), budget_mb=0)
    skipped = {w.relation for w in warmed if w.skipped}
    assert "articles_s_text_t" in skipped and "articles" in skipped
    assert not warmed[-1].skipped  # the TOAST of a short text: empty, it fits
