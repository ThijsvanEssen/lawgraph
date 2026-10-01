"""The shared lookups of the API queries on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries import _helpers


def _doc(key: str, node_type: str, **props: Any) -> dict[str, Any]:
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


def test_the_instrument_and_the_judgments_of_an_article(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments", [_doc("w", "instrument", title="W")]
    )
    store.bulk_insert_or_update_nodes("articles", [_doc("w_1", "article")])
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _doc("a", "judgment", ecli="ECLI:A", date_eff="2020-01-01", text="long"),
            _doc(
                "b", "judgment", ecli="ECLI:B", date_eff="2021-01-01", display_name="B"
            ),
            _doc("c", "judgment", ecli="ECLI:C"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "articles/w_1", "instruments/w", "PART_OF"),
            _edge("2", "judgments/a", "articles/w_1", "REFERS_TO"),
            _edge("3", "judgments/b", "articles/w_1", "REFERS_TO"),
            _edge("4", "judgments/c", "articles/w_1", "REFERS_TO"),
            _edge("5", "documents/d", "articles/w_1", "REFERS_TO"),
        ]
    )
    instrument = _helpers._find_instrument_for_article(store, "articles/w_1")
    assert instrument is not None and instrument["props"] == {"title": "W"}
    assert _helpers._find_instrument_for_article(store, "articles/none") is None
    judgments = _helpers._find_judgments_for_article(store, "articles/w_1")
    assert judgments == [
        {
            "_id": "judgments/b",
            "_key": "b",
            "props": {"ecli": "ECLI:B", "display_name": "B"},
        },
        {
            "_id": "judgments/a",
            "_key": "a",
            "props": {"ecli": "ECLI:A", "display_name": None},
        },
        {
            "_id": "judgments/c",
            "_key": "c",
            "props": {"ecli": "ECLI:C", "display_name": None},
        },
    ]


def test_a_judgment_by_ecli_item_id_or_appno(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _doc("ecli_nl_hr_2020_1", "judgment", ecli="ECLI:NL:HR:2020:1"),
            _doc("echr_001_2", "judgment", appno="123/45"),
            _doc("echr_001_1", "judgment", appno="123/45"),
        ],
    )
    found = _helpers._load_judgment(store, "ECLI:NL:HR:2020:1")
    assert found is not None and found["_key"] == "ecli_nl_hr_2020_1"
    by_appno = _helpers._load_judgment(store, "123/45")
    assert by_appno is not None and by_appno["_key"] == "echr_001_1"
    assert _helpers._load_judgment(store, "nothing") is None
