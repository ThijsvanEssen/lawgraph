"""The instrument a URL names, and the other records of its treaty, on a real
PostgreSQL."""

from __future__ import annotations

from typing import Any

from lawgraph.db import GraphStore
from lawgraph.db.queries.instrument_scope import (
    InstrumentScope,
    resolve_instrument,
    same_treaty,
    scope_of,
    scope_of_node,
)


def _instrument(key: str, labels: list[str] | None = None, **props: Any) -> Any:
    return {"_key": key, "type": "instrument", "labels": labels or [], "props": props}


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _instrument("bwbr0009001", ["BWB"], bwb_id="BWBR0009001"),
            _instrument("32016l0680", ["EU"], celex="32016L0680"),
            _instrument(
                "bwbv0009001", ["BWB"], bwb_id="BWBV0009001", treaty_number="001"
            ),
            _instrument("verdrag_2", ["Verdragenbank"], treaty_number="001"),
            _instrument("verdrag_1", ["Verdragenbank"], treaty_number="001"),
            _instrument("verdrag_3", ["Verdragenbank"], treaty_number="002"),
        ],
    )


def test_an_instrument_by_bwb_id_celex_or_key(store: GraphStore) -> None:
    _seed(store)

    by_bwb = resolve_instrument(store, "BWBR0009001")
    assert by_bwb == {
        "_key": "bwbr0009001",
        "_id": "instruments/bwbr0009001",
        "type": "instrument",
        "labels": ["BWB"],
        "props": {"bwb_id": "BWBR0009001"},
    }
    assert resolve_instrument(store, "bwbr0009001") == by_bwb
    by_celex = resolve_instrument(store, "32016L0680")
    assert by_celex is not None and by_celex["_id"] == "instruments/32016l0680"
    assert resolve_instrument(store, "BWBR0000000") is None

    assert scope_of_node(by_bwb) == InstrumentScope("bwb_id", "BWBR0009001")
    assert scope_of_node(by_celex) == InstrumentScope("celex", "32016L0680")
    assert scope_of(" 32016l0680 ") == InstrumentScope("celex", "32016L0680")


def test_the_other_records_of_a_treaty_by_key(store: GraphStore) -> None:
    _seed(store)
    treaty = resolve_instrument(store, "BWBV0009001")
    assert treaty is not None

    others = same_treaty(store, treaty)

    assert [o["_key"] for o in others] == ["verdrag_1", "verdrag_2"]
    assert others[0] == {
        "_key": "verdrag_1",
        "_id": "instruments/verdrag_1",
        "type": "instrument",
        "labels": ["Verdragenbank"],
        "props": {"treaty_number": "001"},
    }
    verdrag = resolve_instrument(store, "verdrag_1")
    assert verdrag is not None
    assert [o["_key"] for o in same_treaty(store, verdrag)] == [
        "bwbv0009001",
        "verdrag_2",
    ]
    assert same_treaty(store, {"_key": "x", "props": {}}) == []
    assert same_treaty(store, {"_key": "x", "props": {"treaty_number": 1}}) == []
    alone = resolve_instrument(store, "verdrag_3")
    assert alone is not None and same_treaty(store, alone) == []
