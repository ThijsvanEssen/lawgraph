"""What the graph writes and the API serves has one key order, not that of a hash map (D11).

ArangoDB's MERGE keeps the keys of the stored object and adds the new ones in the order of a
hash map, which differs from one execution to the next: the same run gave props, the kinds of
a dossier's papers and the vote counts of an Eerste Kamer faction in another order each time.
"""

from __future__ import annotations

import json

from lawgraph.db import GraphStore


def _props(store: GraphStore, key: str) -> dict[str, object]:
    return next(
        store.query("SELECT props FROM dossiers WHERE key = %(key)s", {"key": key})
    )


def test_an_update_writes_the_props_in_the_order_of_their_keys(database: str) -> None:
    store = GraphStore()
    first = {
        "_key": "1",
        "type": "dossier",
        "labels": ["TK"],
        "props": {"zeta": 1, "b": 2},
    }
    store.bulk_insert_or_update_nodes("dossiers", [first])
    assert list(_props(store, "1")) == ["zeta", "b"]  # an insert keeps its order

    new = {"y": 1, "c": 2, "a": 3, "mid": 4, "B": 5, "a_b": 6, "a1": 7}
    store.bulk_insert_or_update_nodes("dossiers", [{**first, "props": new}])
    assert list(_props(store, "1")) == [
        "a",
        "a_b",
        "a1",
        "B",
        "b",
        "c",
        "mid",
        "y",
        "zeta",
    ]


def test_a_single_upsert_and_edge_meta_are_sorted_too(database: str) -> None:
    from lawgraph.core.models import Node, NodeType

    store = GraphStore()
    node = Node(
        collection="dossiers", type=NodeType.DOSSIER, key="2", props={"title": "x"}
    )
    store.insert_or_update(node)
    store.insert_or_update(
        Node(
            collection="dossiers",
            type=NodeType.DOSSIER,
            key="2",
            props={"label": "2", "kind": "k"},
        )
    )
    assert list(_props(store, "2")) == ["kind", "label", "title"]

    edge = {
        "_key": "e",
        "_from": "dossiers/2",
        "_to": "dossiers/1",
        "relation": "RELATED_TO",
        "source": "tk",
        "status": "canoniek",
        "meta": {"z": 1},
    }
    store.bulk_insert_or_update_edges([edge])
    store.bulk_insert_or_update_edges([{**edge, "meta": {"m": 1, "b": 2, "a": 3}}])
    meta = next(store.query("SELECT doc -> 'meta' FROM edges WHERE key = 'e'"))
    assert json.dumps(meta) == json.dumps({"a": 3, "b": 2, "m": 1, "z": 1})
