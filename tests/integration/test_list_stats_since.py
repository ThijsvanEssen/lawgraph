"""``semantic graph-list-stats --since`` (the daily run) comes to what a run over all does: the
counts of every node from the edges (one that went too), the props of the rows written since
the previous run. A row not written since keeps what it has."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_SAME_AS,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import graph_stats
from lawgraph.db.queries.state import set_state
from lawgraph.pipelines.semantic.graph_list_stats import (
    STATE_KEY,
    GraphListStatsSemanticPipeline,
)

SINCE = dt.datetime(2026, 11, 20, tzinfo=dt.UTC)  # the moment itself is not read


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": "x", "labels": [], "props": props}


def _edge(source: str, relation: str, target: str) -> dict[str, Any]:
    return {
        "key": f"{source}|{relation}|{target}",
        "from_id": source,
        "to_id": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "meta": {},
    }


def _judgment(key: str, ecli: str, date: str) -> dict[str, Any]:
    return _node(key, ecli=ecli, judgment_metadata={"date": date}, text="..." * 500)


def _article(key: str, bwb_id: str, number: str, text: str) -> dict[str, Any]:
    return _node(key, bwb_id=bwb_id, article_number=number, text=text)


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [_node("w", bwb_id="BWBR1", kind="Wet"), _node("v", bwb_id="BWBR2")],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _article("a1", "BWBR1", "I", "Wijzigt de Wet x."),
            _article("a2", "BWBR1", "II", "Deze wet treedt in werking."),
            # one of three changes another: not a wijzigingsregeling
            _article("b1", "BWBR2", "1", "Wijzigt de Wet y."),
            _article("b2", "BWBR2", "2", "Een."),
            _article("b3", "BWBR2", "3", "Twee."),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("j1", "ECLI:NL:HR:2020:1", "2020-01-01"),
            _judgment("j2", "ECLI:NL:RBAMS:2021:2", "2021-02-02"),
            _judgment("j3", "ECLI:NL:GHAMS:2022:3", "2022-03-03"),
            _judgment("j4", "ECLI:NL:GHAMS:2022:4", "2022-03-04"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            *(
                _edge(f"articles/{a}", RELATION_PART_OF, f"instruments/{i}")
                for a, i in (
                    ("a1", "w"),
                    ("a2", "w"),
                    ("b1", "v"),
                    ("b2", "v"),
                    ("b3", "v"),
                )
            ),
            _edge("judgments/j2", RELATION_REFERS_TO, "judgments/j1"),
            _edge("judgments/j3", RELATION_REFERS_TO, "judgments/j4"),
            _edge("judgments/j4", RELATION_SAME_AS, "judgments/j1"),
            _edge("judgments/j3", RELATION_REFERS_TO, "articles/a1"),
            _edge("judgments/j2", RELATION_REFERS_TO, "instruments/w"),
        ]
    )


def _props(store: GraphStore, collection: str, key: str) -> dict[str, Any]:
    doc = store.get_document(collection, key)
    assert doc is not None
    return doc["props"]


def _settled(store: GraphStore) -> None:
    """The graph seeded and the keys written, and a run after that writes nothing: what
    the first one wrote is not written since the run the next one goes on from."""
    _seed(store)
    GraphListStatsSemanticPipeline(store).run()
    assert GraphListStatsSemanticPipeline(store).run().updated == 0


def _left_for_a_run_over_all(store: GraphStore) -> int:
    return GraphListStatsSemanticPipeline(store, dry_run=True).run().skipped


def test_the_daily_run_comes_to_what_a_run_over_all_does(database: str) -> None:
    store = GraphStore()
    _settled(store)
    assert _props(store, "instruments", "v")["amending"] is False
    assert _props(store, "judgments", "j1")["inbound_citation_count"] == 2

    # a day: a judgment dated again, an edge gone and one new, an article gone
    store.bulk_insert_or_update_nodes(
        "judgments", [_judgment("j1", "ECLI:NL:HR:2020:1", "2020-01-09")]
    )
    store.execute(
        "DELETE FROM edges WHERE key = %(key)s",
        {"key": "judgments/j2|REFERS_TO|judgments/j1"},
    )
    store.bulk_insert_or_update_edges(
        [_edge("judgments/j1", RELATION_REFERS_TO, "articles/a2")]
    )
    store.execute("DELETE FROM edges WHERE from_id = 'articles/b3'")
    store.execute("DELETE FROM articles WHERE key = 'b3'")

    result = GraphListStatsSemanticPipeline(store).run(since=SINCE)

    assert result.updated > 0
    assert _left_for_a_run_over_all(store) == 0
    j1 = _props(store, "judgments", "j1")
    assert (j1["date_eff"], j1["inbound_citation_count"]) == ("2020-01-09", 1)
    assert _props(store, "judgments", "j2")["outbound_citation_count"] == 0
    assert _props(store, "articles", "a2")["inbound_citation_count"] == 1
    # one of two articles changes another now: an article that went is seen by the count
    v = _props(store, "instruments", "v")
    assert (v["article_count"], v["amending"]) == (2, True)


def test_a_row_not_written_since_keeps_its_props_until_a_run_over_all(
    database: str,
) -> None:
    store = GraphStore()
    _settled(store)
    store.bulk_insert_or_update_nodes("judgments", [_node("j2", date_eff="1900-01-01")])
    # as if that write came before the previous run
    began = graph_stats.oldest_open_transaction(store)
    set_state(store, STATE_KEY, {"transaction": began})

    GraphListStatsSemanticPipeline(store).run(since=SINCE)
    assert _props(store, "judgments", "j2")["date_eff"] == "1900-01-01"

    GraphListStatsSemanticPipeline(store).run()
    assert _props(store, "judgments", "j2")["date_eff"] == "2021-02-02"


def test_without_a_previous_run_the_daily_run_reads_every_row(database: str) -> None:
    store = GraphStore()
    _settled(store)
    store.bulk_insert_or_update_nodes("judgments", [_node("j2", date_eff="1900-01-01")])
    set_state(store, STATE_KEY, None)

    GraphListStatsSemanticPipeline(store).run(since=SINCE)

    assert _props(store, "judgments", "j2")["date_eff"] == "2021-02-02"


def test_a_dry_run_or_one_collection_keeps_the_previous_mark(database: str) -> None:
    store = GraphStore()
    _settled(store)
    store.bulk_insert_or_update_nodes(
        "judgments", [_judgment("j1", "ECLI:NL:HR:2020:1", "2020-01-09")]
    )

    GraphListStatsSemanticPipeline(store, dry_run=True).run(since=SINCE)
    GraphListStatsSemanticPipeline(store, only="articles").run(since=SINCE)
    GraphListStatsSemanticPipeline(store).run(since=SINCE)

    assert _props(store, "judgments", "j1")["date_eff"] == "2020-01-09"
