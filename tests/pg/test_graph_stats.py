"""``semantic graph-list-stats`` on a real PostgreSQL: the keys it computes and writes."""

from __future__ import annotations

from typing import Any

from lawgraph.core.courts import COURT_BY_CODE
from lawgraph.core.judgments import KIND_OF_COURT_KIND
from lawgraph.db import ArangoStore
from lawgraph.db.queries import graph_stats


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "x",
        "status": "canoniek",
        "meta": {},
    }


def _props(store: ArangoStore, collection: str, key: str) -> dict[str, Any]:
    doc = store.get_document(collection, key)
    assert doc is not None
    return doc["props"]


def test_instruments_count_their_articles_and_what_refers_to_them(
    store: ArangoStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("w", "instrument", bwb_id="BWBR1", kind="Wet", zeta=1),
            _node("x", "instrument"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "articles/a1", "instruments/w", "PART_OF"),
            _edge("2", "annexes/b1", "instruments/w", "PART_OF"),
            _edge("3", "judgments/j", "instruments/w", "REFERS_TO"),
            _edge("4", "judgments/j", "articles/a1", "REFERS_TO"),
            # PART_OF points article → instrument: one the other way is no article of it
            _edge("5", "instruments/w", "articles/a2", "PART_OF"),
        ]
    )
    assert graph_stats.refresh_instruments(store, dry_run=True) == 2
    assert graph_stats.refresh_instruments(store, dry_run=False) == 2
    assert graph_stats.refresh_instruments(store, dry_run=True) == 0
    props = _props(store, "instruments", "w")
    assert props == {
        "article_count": 1,
        "bwb_id": "BWBR1",
        "inbound_citation_count": 2,
        "jurisdiction": "nl",
        "kind": "wet",
        "zeta": 1,
    }
    assert list(props) == sorted(props)  # D11: the keys in order after an update
    assert _props(store, "instruments", "x")["jurisdiction"] == ""


def test_judgments_get_their_court_date_and_citations(store: ArangoStore) -> None:
    hr = COURT_BY_CODE["HR"]
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "a", "judgment", ecli="ECLI:NL:HR:2020:1", meta={"date": "2020-01-01"}
            ),
            _node("b", "judgment", ecli="ECLI:NL:HR:2020:2", decision_kind="arrest"),
            _node("c", "judgment", ecli="ECLI:NL:HR:2020:3", stub=True),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "judgments/b", "judgments/a", "REFERS_TO"),
            _edge("2", "judgments/c", "judgments/b", "REFERS_TO"),
            _edge("3", "judgments/b", "judgments/a", "SAME_AS"),
            _edge("4", "judgments/c", "judgments/a", "REFERS_TO"),
        ]
    )
    assert graph_stats.refresh_judgments(store, dry_run=False) == 3
    a = _props(store, "judgments", "a")
    assert (a["court_code"], a["tier"], a["court_kind"]) == (
        "HR",
        hr.tier,
        hr.court_kind,
    )
    assert a["date_eff"] == "2020-01-01"
    # b cites a, c cites a and c cites b, which is the same decision as a: b and c
    assert a["inbound_citation_count"] == 2
    assert a["decision_kind"] == KIND_OF_COURT_KIND.get(hr.court_kind)
    assert _props(store, "judgments", "b")["decision_kind"] == "arrest"
    assert _props(store, "judgments", "c")["outbound_citation_count"] == 2
    assert graph_stats.refresh_judgments(store, dry_run=True) == 0


def test_committees_count_the_open_dossiers_they_lead(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes(
        "committees",
        [_node("c1", "committee"), _node("c2", "committee", ended_on="2000-01-01")],
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("1", "dossier", closed=False), _node("2", "dossier", closed=True)],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "activities/a", "committees/c1", "LED_BY"),
            _edge("2", "activities/a", "dossiers/1", "ABOUT"),
            _edge("3", "activities/a", "dossiers/2", "ABOUT"),
            _edge("4", "activities/b", "committees/c1", "LED_BY"),
            _edge("5", "activities/b", "dossiers/1", "ABOUT"),
            _edge("6", "activities/a", "committees/c2", "LED_BY"),
        ]
    )
    assert graph_stats.refresh_committees(store, dry_run=False) == 2
    assert _props(store, "committees", "c1")["active_dossier_count"] == 1
    assert _props(store, "committees", "c2")["active_dossier_count"] == 0


def test_articles_count_what_refers_to_and_explains_them(store: ArangoStore) -> None:
    store.bulk_insert_or_update_nodes("articles", [_node("a", "article")])
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "judgments/j", "articles/a", "REFERS_TO"),
            _edge("2", "documents/d", "articles/a", "EXPLAINS"),
            _edge("3", "documents/d", "articles/a", "ABOUT"),
        ]
    )
    assert graph_stats.refresh_articles(store, dry_run=False) == 1
    assert _props(store, "articles", "a") == {"inbound_citation_count": 2}
