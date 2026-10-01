"""The store on a real PostgreSQL: what a pipeline writes and the API reads comes back as it
did from ArangoDB."""

from __future__ import annotations

import json

import psycopg
import pytest

from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, raw_source_doc
from lawgraph.db import store as store_module


def _node(key: str, **props: object) -> dict[str, object]:
    return {"_key": key, "type": "dossier", "labels": ["TK"], "props": props}


def test_a_query_gives_the_value_of_one_column_or_a_dict_of_several(
    store: ArangoStore,
) -> None:
    assert list(store.query("SELECT n FROM generate_series(1, 3) n")) == [1, 2, 3]
    rows = store.query("SELECT 1 AS a, 'x' AS b")
    assert list(rows) == [{"a": 1, "b": "x"}]
    many = store.query("SELECT n FROM generate_series(1, 2500) n", batch_size=100)
    assert sum(many) == 2500 * 2501 // 2


def test_an_upsert_creates_updates_and_leaves_what_did_not_change(
    store: ArangoStore,
) -> None:
    docs = [_node("1", title="a"), _node("2", title="b")]
    assert store.bulk_insert_or_update_nodes("dossiers", docs) == (2, 0)
    assert store.bulk_insert_or_update_nodes("dossiers", docs) == (0, 0)
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("1", title="c")]) == (
        0,
        1,
    )
    assert store.get_document("dossiers", "1") == {
        "_key": "1",
        "_id": "dossiers/1",
        "type": "dossier",
        "labels": ["TK"],
        "props": {"title": "c"},
    }


def test_an_update_merges_props_with_their_keys_in_order_and_labels(
    store: ArangoStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("1", zeta=1, b={"y": 1, "x": 2})]
    )
    update = {
        "_key": "1",
        "type": "dossier",
        "labels": ["EK", "TK"],
        "props": {"alpha": 3},
    }
    store.bulk_insert_or_update_nodes("dossiers", [update])
    doc = store.get_document("dossiers", "1")
    assert doc is not None
    # every key in the order of the collation (D11); a nested object as it was
    assert list(doc["props"]) == ["alpha", "b", "zeta"]
    assert list(doc["props"]["b"]) == ["y", "x"]
    assert doc["labels"] == ["TK", "EK"]


def test_a_key_twice_in_one_batch_is_written_in_its_order(store: ArangoStore) -> None:
    docs = [_node("1", a=1), _node("1", b=2), _node("2", c=3), _node("1", a=4)]
    assert store.bulk_insert_or_update_nodes("dossiers", docs) == (2, 2)
    doc = store.get_document("dossiers", "1")
    assert doc is not None and doc["props"] == {"a": 4, "b": 2}


def test_an_insert_keeps_the_order_of_the_props(store: ArangoStore) -> None:
    tally = {"voor": 76, "tegen": 74, "niet_deelgenomen": 0}
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", z=1, tally=tally, a=2.5)])
    doc = store.get_document("dossiers", "1")
    assert doc is not None
    assert json.dumps(doc["props"]) == json.dumps({"z": 1, "tally": tally, "a": 2.5})


def test_an_edge_update_keeps_created_at_and_merges_meta(store: ArangoStore) -> None:
    edge = {
        "_key": "e1",
        "_from": "articles/a",
        "_to": "judgments/j",
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


def test_the_data_version_follows_what_the_api_serves(store: ArangoStore) -> None:
    first = store.data_version()
    assert len(first) == 16
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", a=1)])
    second = store.data_version()
    assert second != first
    store.bulk_insert_or_update_nodes("dossiers", [_node("1", a=1)])  # unchanged
    store.insert_raw_sources([raw_source_doc(source="tk", kind="k", external_id="x")])
    assert store.data_version() == second


def test_raw_records_keep_their_payload_in_the_payload_store(
    store: ArangoStore,
) -> None:
    doc = raw_source_doc(source="tk", kind="k", external_id="x", payload_text="<xml/>")
    assert store.insert_raw_sources([doc, {**doc, "meta": {"again": True}}]) == []
    stored = next(store.query("SELECT doc FROM raw_sources"))
    assert "payload_text" not in stored and stored["meta"] == {"again": True}
    [read] = store.with_payloads([stored])
    assert read["payload_text"] == "<xml/>"


def test_single_node_writes_and_lookups(store: ArangoStore) -> None:
    node = Node(
        collection="dossiers", type=NodeType.DOSSIER, key="7", props={"title": "x"}
    )
    stored, created = store.insert_or_update(node)
    assert created and stored.props == {"title": "x"}
    _, created = store.insert_or_update(node)
    assert not created
    stub = store.ensure_stub_node("judgments", "ecli_x", "judgment", {"ecli": "ECLI:X"})
    assert stub is not None and stub.props == {"ecli": "ECLI:X", "stub": True}
    again = store.ensure_stub_node("judgments", "ecli_x", "judgment", {"other": 1})
    assert again is not None and again.props == {"ecli": "ECLI:X", "stub": True}
    assert store.has_node("dossiers", "7") and not store.has_node("dossiers", "8")
    assert store.existing_keys("dossiers", ["7", "8"]) == {"7"}
    assert store.count("dossiers") == 1 and store.count("judgments") == 1
    assert store.get_node("dossiers", "8") is None


def test_sizes(store: ArangoStore) -> None:
    assert store.disk_usage()["bytesUsed"] > 0
    assert set(store.collection_sizes()) >= {"dossiers", "edges", "raw_sources"}


def test_a_write_is_sent_again_when_the_database_was_unreachable(
    store: ArangoStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(store_module, "_sleep", waits.append)
    calls = {"n": 0}
    real = store.execute

    def flaky(*args: object, **kwargs: object) -> list[object]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "execute", flaky)
    assert store.bulk_insert_or_update_nodes("dossiers", [_node("1", a=1)]) == (1, 0)
    assert waits == [2.0]


def test_indexes_only_holds_for_its_own_statement(store: ArangoStore) -> None:
    setting = "SELECT current_setting('enable_seqscan')"
    assert list(store.query(setting, indexes_only=True)) == ["off"]
    # SET LOCAL ends with the statement's transaction: the connection goes back as it was
    for _ in range(3):
        assert list(store.query(setting)) == ["on"]
