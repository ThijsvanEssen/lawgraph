"""``/api/stats`` and the node overlays on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore, raw_source_doc
from lawgraph.db.queries import overlay, stats


def _node(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict:
    return {"_key": key, "type": node_type, "labels": labels or [], "props": props}


def _edge(key: str, to: str, relation: str, **doc: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": "documents/d",
        "_to": to,
        "relation": relation,
        "source": "x",
        "status": doc.pop("status", "canoniek"),
        "meta": {},
        **doc,
    }


def test_counts_per_value_in_order_with_unknown_last_written(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("1", "instrument", kind="wet"),
            _node("2", "instrument", kind="Amvb"),
            _node("3", "instrument"),
            _node("4", "instrument", kind=""),
            _node("5", "instrument", kind="publicatie", stub=True),
        ],
    )
    got = stats.get_db_stats(store)
    assert list(got["instruments"]["by_kind"].items()) == [
        ("unknown", 1),  # null, then "", which overwrites it
        ("Amvb", 1),
        ("publicatie", 1),
        ("wet", 1),
    ]
    assert got["stubs"]["instruments"] == 1


def test_coverage_and_data_as_of(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "a",
                "judgment",
                source="rechtspraak",
                tier="hoge_raad",
                court_code="HR",
                court="Hoge Raad",
                date_eff="2020-01-01",
                stub=False,
            ),
            _node(
                "b",
                "judgment",
                source="rechtspraak",
                tier="hoge_raad",
                court_code="HR",
                court="Hoge Raad",
                date_eff="2021-01-01",
                stub=False,
                same_as="judgments/a",
            ),
            _node("c", "judgment", stub=True),
        ],
    )
    coverage = stats.get_judgment_coverage(store)
    assert coverage["courts"] == [
        {
            "source": "rechtspraak",
            "tier": "hoge_raad",
            "court_code": "HR",
            "court": "Hoge Raad",
            "count": 2,
            "first_date": "2020-01-01",
            "last_date": "2021-01-01",
        }
    ]
    assert coverage["stubs"] == 1
    assert coverage["replaced"] == [
        {"source": "rechtspraak", "tier": "hoge_raad", "court_code": "HR", "count": 1}
    ]
    store.insert_raw_sources(
        [
            {
                **raw_source_doc(source="rechtspraak", kind="k", external_id="1"),
                "fetched_at": "2026-01-01T00:00:00Z",
            },
            {
                **raw_source_doc(source="bwb", kind="k", external_id="1"),
                "fetched_at": "2026-02-01T00:00:00Z",
            },
        ]
    )
    assert stats.get_data_as_of(store, today="2026-10-01") == {
        "bwb": {"retrieved_at": "2026-02-01T00:00:00Z", "newest": None},
        "rechtspraak": {"retrieved_at": "2026-01-01T00:00:00Z", "newest": "2021-01-01"},
    }


def test_data_as_of_takes_the_newest_fetch_of_each_source(store: GraphStore) -> None:
    def raw(source: str | None, external_id: str, fetched_at: str | None) -> dict:
        return {
            **raw_source_doc(source="x", kind="k", external_id=external_id),
            "source": source,
            "fetched_at": fetched_at,
        }

    store.insert_raw_sources(
        [
            raw("tk", "1", "2026-03-01T00:00:00Z"),
            raw("tk", "2", "2026-05-01T00:00:00Z"),
            raw("tk", "3", None),
            raw("EU", "4", "2026-01-01T00:00:00Z"),
            raw("bwb", "5", "2026-02-01T00:00:00Z"),
            raw(None, "6", "2026-04-01T00:00:00Z"),
        ]
    )
    found = stats.get_data_as_of(store, today="2026-10-01")
    # a record without a source first, then the sources in the order of the collation
    assert list(found) == [None, "bwb", "EU", "tk"]
    assert [row["retrieved_at"] for row in found.values()] == [
        "2026-04-01T00:00:00Z",
        "2026-02-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
    ]


def test_overlays_by_node_in_order(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "articles/b", "AMENDS", status="voorgesteld"),
            _edge("2", "articles/a", "AMENDS", status="voorgesteld"),
            _edge("3", "articles/a", "REFERS_TO", created_at="2000-01-01"),
            _edge("4", "dossiers/1", "ABOUT", created_at="2999-01-01"),
        ]
    )
    assert list(overlay.get_in_flux_counts(store).items()) == [
        ("articles/a", 1),
        ("articles/b", 1),
    ]
    heat = overlay.get_heat_counts(store)
    assert heat == {"dossiers/1": 1, "articles/a": 2, "articles/b": 1}
    assert overlay.get_heat_counts(store, min_count=2) == {"articles/a": 2}


def test_the_changes_in_flux_are_kept_while_the_edges_stand_still(
    store: GraphStore,
) -> None:
    """Every proposed edge is read (5.9 s on prod): kept until the edges change, then
    counted again, whatever is written to other tables."""
    store.bulk_insert_or_update_edges(
        [_edge("1", "articles/a", "AMENDS", status="voorgesteld")]
    )
    assert overlay.get_in_flux_counts(store) == {"articles/a": 1}
    calls = []
    query = store.query

    def counted(statement, params=None, **options):  # type: ignore[no-untyped-def]
        if "%(proposed)s" in str(statement):  # the count, not a read of the version
            calls.append(1)
        return query(statement, params, **options)

    store.query = counted  # type: ignore[method-assign]
    try:
        store.bulk_insert_or_update_nodes(
            "instruments",
            [{"_key": "x", "type": "instrument", "labels": [], "props": {}}],
        )
        assert overlay.get_in_flux_counts(store) == {"articles/a": 1}
        assert calls == []  # kept: no edge changed
        store.bulk_insert_or_update_edges(
            [_edge("2", "articles/b", "AMENDS", status="voorgesteld")]
        )
        assert overlay.get_in_flux_counts(store) == {"articles/a": 1, "articles/b": 1}
    finally:
        store.query = query  # type: ignore[method-assign]


def test_heat_of_named_nodes_is_their_part_of_the_whole_map(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "articles/a", "REFERS_TO", created_at="2000-01-01"),
            # recent and a citation of an article: it counts in both, as in the whole map
            _edge("2", "articles/a", "REFERS_TO", created_at="2999-01-01"),
            _edge("3", "dossiers/1", "ABOUT", created_at="2999-01-01"),
            _edge("4", "dossiers/1", "ABOUT", created_at="2999-01-01"),
            _edge("5", "dossiers/2", "ABOUT", created_at="2999-01-01"),
            _edge("6", "articles/b", "AMENDS"),
        ]
    )
    whole = overlay.get_heat_counts(store)
    assert whole == {"articles/a": 3, "articles/b": 1, "dossiers/1": 2, "dossiers/2": 1}
    named = ["articles/a", "dossiers/2", "instruments/none"]
    for min_count in (1, 2):
        assert overlay.get_heat_counts(store, ids=named, min_count=min_count) == {
            k: v for k, v in whole.items() if k in named and v >= min_count
        }
    assert overlay.get_heat_counts(store, ids=[]) == {}
    # the whole map, the highest counts first kept (the id settles ties)
    assert overlay.get_heat_counts(store, limit=2) == {"articles/a": 3, "dossiers/1": 2}
    assert overlay.get_heat_counts(store, limit=3) == {
        "articles/a": 3,
        "articles/b": 1,
        "dossiers/1": 2,
    }


def test_after_a_poll_of_judgments_the_coverage_of_before_is_answered_at_once(
    store: GraphStore, monkeypatch: Any
) -> None:
    """A request does not wait ``STALE_WAIT`` for the new counts (2.2 s on 10 Oct): it
    takes those of before while they compute; the warm-up waits for them."""
    import time

    from lawgraph.api.routes import stats as stats_route
    from lawgraph.db import store as store_module

    monkeypatch.setattr(stats_route, "get_judgment_coverage", lambda s: ["old"])
    assert stats_route.coverage_data(store) == ["old"]
    store.bulk_insert_or_update_nodes(
        "judgments", [{"_key": "j", "type": "judgment", "labels": [], "props": {}}]
    )

    def slow(s: Any) -> list[str]:
        time.sleep(0.5)
        return ["new"]

    monkeypatch.setattr(stats_route, "get_judgment_coverage", slow)
    token = store_module.set_read_deadline(5.0)
    try:
        started = time.monotonic()
        assert stats_route.coverage_data(store) == ["old"]
        assert time.monotonic() - started < 0.3
    finally:
        store_module.reset_read_deadline(token)
    assert stats_route.coverage_data(store) == ["new"]  # the warm-up waits
