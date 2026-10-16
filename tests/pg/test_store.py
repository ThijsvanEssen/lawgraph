"""The store on a real PostgreSQL: what a pipeline writes and the API reads comes back as it
was written."""

from __future__ import annotations

import json
import time
from typing import Any

import psycopg
import pytest

from lawgraph.config.settings import DB_BACKGROUND_POOL_SIZE
from lawgraph.core.models import Node
from lawgraph.db import GraphStore, raw_source_doc, request_context
from lawgraph.db import store as store_module


def _node(key: str, **props: object) -> dict[str, object]:
    return {"key": key, "type": "dossier", "labels": ["TK"], "props": props}


def test_a_query_gives_the_value_of_one_column_or_a_dict_of_several(
    store: GraphStore,
) -> None:
    assert list(store.query("SELECT n FROM generate_series(1, 3) n")) == [1, 2, 3]
    rows = store.query("SELECT 1 AS a, 'x' AS b")
    assert list(rows) == [{"a": 1, "b": "x"}]
    many = store.query("SELECT n FROM generate_series(1, 2500) n", batch_size=100)
    assert sum(many) == 2500 * 2501 // 2


def test_an_upsert_creates_updates_and_leaves_what_did_not_change(
    store: GraphStore,
) -> None:
    docs = [_node("1", title="a"), _node("2", title="b")]
    assert store.bulk_insert_or_update_nodes("dossiers", docs) == (2, 0)
    assert store.bulk_insert_or_update_nodes("dossiers", docs) == (0, 0)
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("1", title="c")]) == (
        0,
        1,
    )
    assert store.get_document("dossiers", "1") == {
        "key": "1",
        "id": "dossiers/1",
        "type": "dossier",
        "labels": ["TK"],
        "props": {"title": "c"},
    }


def test_an_update_merges_props_with_their_keys_in_order_and_labels(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("1", same_number_count=1, ek_bill={"y": 1, "x": 2})]
    )
    update = {
        "key": "1",
        "type": "dossier",
        "labels": ["EK", "TK"],
        "props": {"cabinet": 3},
    }
    store.bulk_insert_or_update_nodes("dossiers", [update])
    doc = store.get_document("dossiers", "1")
    assert doc is not None
    # every key in the order of the collation (D11); a nested object as it was
    assert list(doc["props"]) == ["cabinet", "ek_bill", "same_number_count"]
    assert list(doc["props"]["ek_bill"]) == ["y", "x"]
    assert doc["labels"] == ["TK", "EK"]


def test_an_update_writes_the_props_in_the_order_of_their_keys(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", title=1, number=2)])
    new = {
        "opened_on_basis": 1,
        "opened_on": 2,
        "kind_basis": 3,
        "kind": 4,
        "cabinet": 5,
    }
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", **new)])
    doc = store.get_document("dossiers", "1")
    assert doc is not None
    assert list(doc["props"]) == [
        "cabinet",
        "kind",
        "kind_basis",
        "number",
        "opened_on",
        "opened_on_basis",
        "title",
    ]


def test_merged_keys_follow_the_collation(store: GraphStore) -> None:
    """Underscores, digits and capitals as the collation orders them (``lg_update``)."""
    new = {"y": 1, "c": 2, "a": 3, "mid": 4, "B": 5, "a_b": 6, "a1": 7}
    merged = next(
        store.query(
            "SELECT lg_update(%(a)s::json, %(b)s::json)",
            {"a": json.dumps({"zeta": 1, "b": 2}), "b": json.dumps(new)},
        )
    )
    assert list(merged) == ["a", "a_b", "a1", "B", "b", "c", "mid", "y", "zeta"]


def test_a_single_upsert_and_edge_meta_are_sorted_too(store: GraphStore) -> None:
    store.insert_or_update(Node(collection="dossiers", key="2", props={"title": "x"}))
    store.insert_or_update(
        Node(collection="dossiers", key="2", props={"label": "2", "kind": "k"})
    )
    doc = store.get_document("dossiers", "2")
    assert doc is not None and list(doc["props"]) == ["kind", "label", "title"]

    edge = {
        "key": "e",
        "from_id": "dossiers/2",
        "to_id": "dossiers/1",
        "relation": "RELATED_TO",
        "source": "tk",
        "status": "canoniek",
        "meta": {"z": 1},
    }
    store.bulk_insert_or_update_edges([edge])
    store.bulk_insert_or_update_edges([{**edge, "meta": {"m": 1, "b": 2, "a": 3}}])
    meta = next(store.query("SELECT doc -> 'meta' FROM edges WHERE key = 'e'"))
    assert json.dumps(meta) == json.dumps({"a": 3, "b": 2, "m": 1, "z": 1})


def test_a_key_twice_in_one_batch_is_written_in_its_order(store: GraphStore) -> None:
    docs = [
        _node("1", title=1),
        _node("1", number=2),
        _node("2", suffix=3),
        _node("1", title=4),
    ]
    assert store.bulk_insert_or_update_nodes("dossiers", docs) == (2, 2)
    doc = store.get_document("dossiers", "1")
    assert doc is not None and doc["props"] == {"title": 4, "number": 2}


def test_an_insert_keeps_the_order_of_the_props(store: GraphStore) -> None:
    tally = {"voor": 76, "tegen": 74, "niet_deelgenomen": 0}
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("1", title=1, tk_decision=tally, order=2.5)]
    )
    doc = store.get_document("dossiers", "1")
    assert doc is not None
    assert json.dumps(doc["props"]) == json.dumps(
        {"title": 1, "tk_decision": tally, "order": 2.5}
    )


def test_an_edge_update_keeps_created_at_and_merges_meta(store: GraphStore) -> None:
    edge = {
        "key": "e1",
        "from_id": "articles/a",
        "to_id": "judgments/j",
        "relation": "REFERS_TO",
        "source": "rechtspraak",
        "status": "canoniek",
        "created_at": "2026-01-01T00:00:00+00:00",
        "meta": {"b": 1},
        "confidence": 0.9,
    }
    assert store.bulk_insert_or_update_edges([edge]) == (1, 0)
    assert store.bulk_insert_or_update_edges([edge]) == (0, 0)
    later = {**edge, "created_at": "2027-01-01", "meta": {"a": 2}}
    del later["confidence"]
    assert store.bulk_insert_or_update_edges([later]) == (0, 1)
    row = next(store.query("SELECT key, from_id, to_id, doc FROM edges"))
    assert row["doc"]["created_at"] == "2026-01-01T00:00:00+00:00"
    assert row["doc"]["meta"] == {"b": 1, "a": 2}
    assert row["doc"]["confidence"] is None


def test_an_update_that_only_adds_nulls_is_not_written(store: GraphStore) -> None:
    """A prop set to null is the same as a missing one. A step that
    writes ``None`` for what a node lacks (``semantic tk-government`` on a dossier nobody
    signed) leaves it as it is."""
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", title="a")])
    version = store.data_version()
    nulls = _node("1", ministry=None, initiative=None, cabinet=None)
    assert store.bulk_insert_or_update_nodes("dossiers", [nulls]) == (0, 0)
    doc = store.get_document("dossiers", "1")
    assert doc is not None and doc["props"] == {"title": "a"}
    assert store.data_version() == version
    # a null inside an object, inside an array too, is the same as a missing one ...
    nested = {"ek_bill": {"b": 1}, "phases": [{"c": 1}]}
    store.bulk_insert_or_update_nodes("dossiers", [_node("2", **nested)])
    same = {"ek_bill": {"b": 1, "x": None}, "phases": [{"c": 1, "x": None}]}
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("2", **same)]) == (0, 0)
    # ... and so is a null an array ends in (what the shorter lacks compares as null),
    # but not one before an element
    ending = {"phases": [{"c": 1}, None]}
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("2", **ending)]) == (
        0,
        0,
    )
    before = {"phases": [None, {"c": 1}]}
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("2", **before)]) == (
        0,
        1,
    )


def test_a_real_change_is_written_whole_nulls_included(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("1", title="a", ministry="bz")]
    )
    change = _node("1", title="b", ministry=None, cabinet=None)
    assert store.bulk_insert_or_update_nodes("dossiers", [change]) == (0, 1)
    doc = store.get_document("dossiers", "1")
    assert doc is not None
    # the nulls of a written update are kept
    assert doc["props"] == {"cabinet": None, "ministry": None, "title": "b"}
    # a value set to null where there was one is a change
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("1", title=None)]) == (
        0,
        1,
    )


def test_an_edge_whose_meta_only_gains_nulls_is_not_written(store: GraphStore) -> None:
    edge = {
        "key": "e1",
        "from_id": "members/m",
        "to_id": "factions/f",
        "relation": "MEMBER_OF",
        "source": "tk",
        "meta": {"from_date": "2020-01-01"},
    }
    assert store.bulk_insert_or_update_edges([edge]) == (1, 0)
    nulls = {**edge, "meta": {"to_date": None, "role": None}}
    assert store.bulk_insert_or_update_edges([nulls]) == (0, 0)
    row = next(store.query("SELECT doc FROM edges"))
    assert row["meta"] == {"from_date": "2020-01-01"}
    later = {**edge, "meta": {"to_date": "2021-01-01", "role": None}}
    assert store.bulk_insert_or_update_edges([later]) == (0, 1)
    row = next(store.query("SELECT doc FROM edges"))
    assert row["meta"] == {
        "from_date": "2020-01-01",
        "role": None,
        "to_date": "2021-01-01",
    }


def test_the_data_version_follows_what_the_api_serves(store: GraphStore) -> None:
    first = store.data_version()
    assert len(first) == 16
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", title="a")])
    second = store.data_version()
    assert second != first
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", title="a")])  # unchanged
    store.insert_raw_sources([raw_source_doc(source="tk", kind="k", external_id="x")])
    assert store.data_version() == second


def test_raw_records_keep_their_payload_in_the_payload_store(
    store: GraphStore,
) -> None:
    doc = raw_source_doc(source="tk", kind="k", external_id="x", payload_text="<xml/>")
    store.insert_raw_sources([doc, {**doc, "meta": {"again": True}}])
    stored = next(store.query("SELECT doc FROM raw_sources"))
    assert "payload_text" not in stored and stored["meta"] == {"again": True}
    [read] = store.with_payloads([stored])
    assert read["payload_text"] == "<xml/>"


def test_single_node_writes_and_lookups(store: GraphStore) -> None:
    node = Node(collection="dossiers", key="7", props={"title": "x"})
    stored, created = store.insert_or_update(node)
    assert created and stored.props == {"title": "x"}
    _, created = store.insert_or_update(node)
    assert not created
    stub = store.ensure_stub_node("judgments", "ecli_x", {"ecli": "ECLI:X"})
    assert stub is not None and stub.props == {"ecli": "ECLI:X", "stub": True}
    again = store.ensure_stub_node("judgments", "ecli_x", {"other": 1})
    assert again is not None and again.props == {"ecli": "ECLI:X", "stub": True}
    assert store.has_node("dossiers", "7") and not store.has_node("dossiers", "8")
    assert store.existing_keys("dossiers", ["7", "8"]) == {"7"}
    assert store.count("dossiers") == 1 and store.count("judgments") == 1
    assert store.get_node("dossiers", "8") is None


def test_sizes(store: GraphStore) -> None:
    assert store.database_size() > 0
    assert set(store.collection_sizes()) >= {"dossiers", "edges", "raw_sources"}


def test_a_write_is_sent_again_when_the_database_was_unreachable(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(store_module, "_sleep", waits.append)
    calls = {"n": 0}
    real = store.pool.connection

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return real(*args, **kwargs)

    monkeypatch.setattr(store.pool, "connection", flaky)
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("1", title="a")]) == (
        1,
        0,
    )
    assert waits == [2.0]


def test_indexes_only_holds_for_its_own_statement(store: GraphStore) -> None:
    setting = "SELECT current_setting('enable_seqscan')"
    assert list(store.query(setting, indexes_only=True)) == ["off"]
    # SET LOCAL ends with the statement's transaction: the connection goes back as it was
    for _ in range(3):
        assert list(store.query(setting)) == ["on"]


def test_hash_joins_holds_for_its_own_statement(store: GraphStore) -> None:
    setting = "SELECT current_setting('enable_nestloop')"
    assert list(store.query(setting, hash_joins=True)) == ["off"]
    for _ in range(3):
        assert list(store.query(setting)) == ["on"]


def test_the_connections_of_the_pool_run_without_jit(store: GraphStore) -> None:
    with store.pool.connection() as conn:
        assert conn.execute("SHOW jit").fetchone() == ("off",)
    # and so do the reads of the store, on whichever connection they get
    assert list(store.query("SELECT current_setting('jit')")) == ["off"]


def test_a_read_has_a_ceiling_of_its_own_and_says_so(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``LAWGRAPH_READ_TIMEOUT_MS`` holds for every statement of a read; one that runs past
    it is cancelled with an error that names the setting and the statement."""
    monkeypatch.setattr(request_context, "READ_TIMEOUT_MS", 1234)
    assert list(store.query("SELECT current_setting('statement_timeout')")) == [
        "1234ms"
    ]
    monkeypatch.setattr(request_context, "READ_TIMEOUT_MS", 200)
    with pytest.raises(request_context.ReadTimedOut, match="LAWGRAPH_READ_TIMEOUT_MS"):
        list(store.query("SELECT pg_sleep(2) AS slept"))
    # the connection goes back as it was: the next read runs
    assert list(store.query("SELECT 1")) == [1]


def test_own_activity_names_the_long_statements_of_this_process(
    store: GraphStore,
) -> None:
    import threading
    import time

    sleeper = threading.Thread(
        target=lambda: list(store.query("SELECT pg_sleep(3) AS watched_sleep"))
    )
    sleeper.start()
    try:
        found: list[dict[str, Any]] = []
        for _ in range(40):
            found = [
                row
                for row in store_module.own_activity(0.5)
                if "watched_sleep" in row["query"]
            ]
            if found:
                break
            time.sleep(0.1)
    finally:
        sleeper.join()
    # a streamed read runs as a FETCH; the watchdog names the read behind it
    assert found and found[0]["state"] == "active"
    assert found[0]["query"].startswith("FETCH")
    assert "a read of: SELECT pg_sleep(3) AS watched_sleep" in found[0]["query"]


def test_a_request_waits_for_a_connection_no_longer_than_its_deadline(
    store: GraphStore,
) -> None:
    """Every connection of the pool busy: a read of a request gives up at its deadline."""
    held = [store.pool.getconn() for _ in range(store.pool.max_size)]
    token = request_context.set_read_deadline(0.3)
    try:
        with pytest.raises(request_context.ReadTimedOut, match="No connection"):
            list(store.query("SELECT 1"))
    finally:
        request_context.reset_read_deadline(token)
        for conn in held:
            store.pool.putconn(conn)
    assert list(store.query("SELECT 1")) == [1]


def test_a_read_in_the_background_has_connections_of_its_own(
    store: GraphStore,
) -> None:
    """Every connection of the requests busy: what the API computes in the background
    reads on its own pool, and a request is never kept waiting by it."""
    held = [store.pool.getconn() for _ in range(store.pool.max_size)]
    try:
        with request_context.in_background():
            assert list(store.query("SELECT 1 AS one")) == [1]
    finally:
        for conn in held:
            store.pool.putconn(conn)
    assert store._background_pool is not None
    assert store._background_pool.max_size == DB_BACKGROUND_POOL_SIZE


def test_the_use_of_both_pools_is_told(store: GraphStore) -> None:
    """``/api/health`` shows whether requests or the background wait for a connection."""
    held = store.pool.getconn()
    try:
        usage = store.pool_usage()
    finally:
        store.pool.putconn(held)
    requests = usage["requests"]
    assert requests is not None
    assert requests["size"] == store.pool.max_size
    assert requests["free"] == store.pool.max_size - 1
    assert requests["waiting"] == 0
    with request_context.in_background():
        list(store.query("SELECT 1 AS one"))
    background = store.pool_usage()["background"]
    assert background is not None
    assert background["size"] == DB_BACKGROUND_POOL_SIZE


def test_health_names_the_version_of_the_api(store: GraphStore) -> None:
    """A deploy checks the version it put live against its tag."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    app.dependency_overrides[get_store] = lambda: store
    try:
        health = TestClient(app).get("/api/health").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert health["version"] == app.version
    assert health["status"] == "ok"


def test_analyze_changed_analyzes_the_tables_with_changed_rows_alone(
    store: GraphStore, database_url: str
) -> None:
    # a connection that ends reports what it changed to the statistics at once
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE written (n int)")
        conn.execute("INSERT INTO written VALUES (1)")
    changed = (
        "SELECT coalesce(sum(n_mod_since_analyze), 0)::int FROM pg_stat_user_tables"
        " WHERE relname = 'written'"
    )
    for _ in range(50):
        if next(store.query(changed)):
            break
        time.sleep(0.1)

    def analyzed(table: str) -> bool:
        statement = (
            "SELECT last_analyze IS NOT NULL FROM pg_stat_user_tables"
            " WHERE relname = %(table)s"
        )
        return bool(next(store.query(statement, {"table": table})))

    store.analyze_changed()
    assert analyzed("written")
    assert not analyzed("documents")
