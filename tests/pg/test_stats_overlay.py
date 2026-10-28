"""``/api/stats`` and the node overlays on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, raw_source_doc, request_context
from lawgraph.db.queries import overlay, stats
from tests.pg.plans import recorded


def _node(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict:
    return {"key": key, "type": node_type, "labels": labels or [], "props": props}


def _edge(key: str, to: str, relation: str, **doc: Any) -> dict[str, Any]:
    return {
        "key": key,
        "from_id": "documents/d",
        "to_id": to,
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


def _fetched(found: dict[Any, Any]) -> dict[Any, Any]:
    """Of ``get_data_as_of`` the sources fetched from, their ``retrieved_at`` and ``newest``
    (``tests/pg/test_data_as_of.py`` holds the others and ``completeness``)."""
    return {
        source: {"retrieved_at": row["retrieved_at"], "newest": row["newest"]}
        for source, row in found.items()
        if row["retrieved_at"]
    }


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
    assert _fetched(stats.get_data_as_of(store, today="2026-10-01")) == {
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
    found = _fetched(stats.get_data_as_of(store, today="2026-10-01"))
    # a record without a source first, then the sources in the order of the collation
    assert list(found) == [None, "bwb", "EU", "tk"]
    assert [row["retrieved_at"] for row in found.values()] == [
        "2026-04-01T00:00:00Z",
        "2026-02-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
    ]


def _open_dossier(store: GraphStore, key: str = "1", **props: Any) -> None:
    """The dossier *key*, not ended unless *props* say so."""
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node(key, "dossier", number=key, **{"closed": False, **props})]
    )


def test_overlays_by_node_in_order(store: GraphStore) -> None:
    _open_dossier(store)  # of documents/d (``ABOUT``)
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
    named = ["articles/a", "articles/b", "dossiers/1"]
    heat = overlay.get_heat_counts(store, ids=named)
    assert heat == {"dossiers/1": 1, "articles/a": 2, "articles/b": 1}
    assert overlay.get_heat_counts(store, min_count=2, ids=named) == {"articles/a": 2}


def test_the_dossiers_in_flux_are_the_dossiers_of_the_open_changes(
    store: GraphStore,
) -> None:
    """Each node its count as ``get_in_flux_counts`` has it, and the dossiers of the papers
    that propose its changes, with the first bill of each by date."""
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("a1", "document", kind="Amendement", date="2025-03-01"),
            _node(
                "b2",
                "document",
                kind="Voorstel van wet (initiatiefvoorstel)",
                date="2025-02-01",
            ),
            _node("b1", "document", kind="Voorstel van wet", date="2025-01-01"),
            _node("m1", "document", kind="Memorie van toelichting", date="2024-12-01"),
            _node("x1", "document", kind="Brief regering"),
            _node("y1", "document", kind="Amendement"),
            _node("z1", "document", kind="Amendement"),
        ],
    )
    _open_dossier(store, "36000", title="Wet x")
    # its end not derived yet: open, and said so
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("35000", "dossier", number="35000")]
    )
    # its law published: ended
    _open_dossier(store, "34000", closed=True, outcome="aangenomen")

    def proposed(key: str, paper: str, to: str) -> dict[str, Any]:
        return _edge(
            key, to, "AMENDS", status="voorgesteld", from_id=f"documents/{paper}"
        )

    def member(key: str, paper: str, dossier: str, relation: str = "PART_OF") -> dict:
        return _edge(key, f"dossiers/{dossier}", relation, from_id=f"documents/{paper}")

    store.bulk_insert_or_update_edges(
        [
            *(member(f"m{p}", p, "36000") for p in ("a1", "b1", "b2", "m1")),
            member("my1", "y1", "35000", "ABOUT"),
            member("mz1", "z1", "34000"),
            member("ma1", "a1", "34000"),  # also in an ended dossier
            proposed("1", "a1", "articles/a"),
            proposed("2", "m1", "articles/a"),
            proposed("3", "x1", "articles/a"),  # a paper in no dossier
            proposed("4", "y1", "articles/a"),
            proposed("5", "a1", "articles/b"),
            _edge("6", "articles/c", "AMENDS", from_id="documents/a1"),  # enacted
            proposed("7", "z1", "articles/d"),  # of an ended dossier alone
        ]
    )
    named = ["articles/a", "articles/b", "articles/c", "articles/d"]
    found = overlay.get_in_flux_dossiers(store, named)
    counts = overlay.get_in_flux_counts(store)
    assert counts == {"articles/a": 3, "articles/b": 1}
    assert {node: entry["count"] for node, entry in found.items()} == counts
    x = {"id": "dossiers/36000", "number": "36000", "title": "Wet x"}
    x |= {"bill_id": "documents/b1", "closed_known": True}
    assert found["articles/a"]["dossiers"] == [
        {**x, "count": 2},
        {
            "id": "dossiers/35000",
            "number": "35000",
            "title": None,
            "bill_id": None,
            "closed_known": False,
            "count": 1,
        },
    ]
    assert found["articles/b"]["dossiers"] == [{**x, "count": 1}]


def test_the_changes_in_flux_are_kept_while_the_edges_stand_still(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every proposed edge is read (5.9 s on prod): kept until the edges or the dossiers
    change, then counted again, whatever is written to other tables."""
    _open_dossier(store)
    store.bulk_insert_or_update_edges(
        [
            _edge("m", "dossiers/1", "PART_OF"),
            _edge("1", "articles/a", "AMENDS", status="voorgesteld"),
        ]
    )
    assert overlay.get_in_flux_counts(store) == {"articles/a": 1}
    seen = recorded(store, monkeypatch)
    store.bulk_insert_or_update_nodes(
        "instruments",
        [{"key": "x", "type": "instrument", "labels": [], "props": {}}],
    )
    assert overlay.get_in_flux_counts(store) == {"articles/a": 1}
    # the count, not a read of the version
    calls = [1 for c in seen if "%(proposed)s" in c.text]
    assert calls == []  # kept: no edge changed
    store.bulk_insert_or_update_edges(
        [_edge("2", "articles/b", "AMENDS", status="voorgesteld")]
    )
    assert overlay.get_in_flux_counts(store) == {"articles/a": 1, "articles/b": 1}
    _open_dossier(store, closed=True)
    assert overlay.get_in_flux_counts(store) == {}


def test_heat_of_named_nodes_and_of_the_whole_map(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "articles/a", "REFERS_TO", created_at="2000-01-01"),
            # recent and a citation of an article: it counts in both
            _edge("2", "articles/a", "REFERS_TO", created_at="2999-01-01"),
            _edge("3", "dossiers/1", "ABOUT", created_at="2999-01-01"),
            _edge("4", "dossiers/1", "ABOUT", created_at="2999-01-01"),
            _edge("5", "dossiers/2", "ABOUT", created_at="2999-01-01"),
            _edge("6", "articles/b", "AMENDS"),
        ]
    )
    named = ["articles/a", "dossiers/2", "instruments/none"]
    assert overlay.get_heat_counts(store, ids=named) == {
        "articles/a": 3,
        "dossiers/2": 1,
    }
    assert overlay.get_heat_counts(store, ids=named, min_count=2) == {"articles/a": 3}
    assert overlay.get_heat_counts(store, ids=[]) == {}
    # the whole map, the highest counts first kept (the id settles ties)
    overlay.store_heat(store, 50)
    assert overlay.stored_heat(store, 6, 1, 10) == {
        "articles/a": 3,
        "articles/b": 1,
        "dossiers/1": 2,
        "dossiers/2": 1,
    }
    assert overlay.stored_heat(store, 6, 1, 2) == {"articles/a": 3, "dossiers/1": 2}
    assert overlay.stored_heat(store, 6, 1, 3) == {
        "articles/a": 3,
        "articles/b": 1,
        "dossiers/1": 2,
    }


def test_after_a_poll_of_judgments_the_coverage_of_before_is_answered_at_once(
    store: GraphStore, monkeypatch: Any
) -> None:
    """A request does not wait ``STALE_WAIT`` for the new counts (2.2 s on 10 Oct): it
    takes those of before while they compute; the warm-up waits for them."""
    import threading

    from lawgraph.api.routes import stats as stats_route
    from tests.fakes import PATIENCE

    monkeypatch.setattr(stats_route, "get_judgment_coverage", lambda s: {"of": "old"})
    assert stats_route.coverage_data(store) == {"of": "old"}
    store.bulk_insert_or_update_nodes(
        "judgments", [{"key": "j", "type": "judgment", "labels": [], "props": {}}]
    )

    release = threading.Event()

    def slow(s: Any) -> dict[str, str]:
        release.wait(PATIENCE)
        return {"of": "new"}

    monkeypatch.setattr(stats_route, "get_judgment_coverage", slow)
    token = request_context.set_read_deadline(5.0)
    try:
        assert stats_route.coverage_data(store) == {"of": "old"}
        assert not release.is_set()  # answered while the new counts compute
    finally:
        request_context.reset_read_deadline(token)
        release.set()
    assert stats_route.coverage_data(store) == {"of": "new"}  # the warm-up waits


def test_data_as_of_holds_one_connection_at_a_time(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sources are read before the newest record of each is asked: a query whose rows
    are still being read holds a connection of the pool."""
    store.insert_raw_sources(
        [
            {
                **raw_source_doc(source=source, kind="k", external_id="1"),
                "fetched_at": "2026-02-01T00:00:00Z",
            }
            for source in ("rechtspraak", "tk")
        ]
    )
    query = store.query
    reading = [0, 0]  # now, most

    def counted(*args: Any, **kwargs: Any) -> Any:
        reading[0] += 1
        reading[1] = max(reading[1], reading[0])
        try:
            yield from query(*args, **kwargs)
        finally:
            reading[0] -= 1

    monkeypatch.setattr(store, "query", counted)
    found = stats.get_data_as_of(store, today="2026-10-01")
    assert set(_fetched(found)) == {"rechtspraak", "tk"}
    assert reading[1] == 1
