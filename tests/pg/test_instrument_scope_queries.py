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
    return {"key": key, "type": "instrument", "labels": labels or [], "props": props}


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
        "key": "bwbr0009001",
        "id": "instruments/bwbr0009001",
        "type": "instrument",
        "labels": ["BWB"],
        "props": {"bwb_id": "BWBR0009001"},
    }
    assert resolve_instrument(store, "bwbr0009001") == by_bwb
    by_celex = resolve_instrument(store, "32016L0680")
    assert by_celex is not None and by_celex["id"] == "instruments/32016l0680"
    assert resolve_instrument(store, "BWBR0000000") is None

    assert scope_of_node(by_bwb) == InstrumentScope("bwb_id", "BWBR0009001")
    assert scope_of_node(by_celex) == InstrumentScope("celex", "32016L0680")
    assert scope_of(" 32016l0680 ") == InstrumentScope("celex", "32016L0680")


def test_the_official_number_of_a_law_of_the_staatsblad_names_the_law(
    store: GraphStore,
) -> None:
    """``STB-2026-56`` names the law the publication enacted (``wet_stb_2026_56``), as the
    sub-routes and ``/wetten/STB-2026-56`` read it; the publication keeps its own key. A
    number without a law names nothing."""
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _instrument("stb_2026_56", ["Staatsblad"]),
            _instrument("wet_stb_2026_56", ["Staatsblad"]),
            _instrument("stb_2026_57", ["Staatsblad"]),
        ],
    )

    for name in ("STB-2026-56", "stb-2026-56", "wet_stb_2026_56"):
        law = resolve_instrument(store, name)
        assert law is not None and law["key"] == "wet_stb_2026_56", name
    publication = resolve_instrument(store, "stb_2026_56")
    assert publication is not None and publication["key"] == "stb_2026_56"
    assert resolve_instrument(store, "STB-2026-57") is None
    law = resolve_instrument(store, "STB-2026-56")
    assert law is not None and scope_of_node(law) == scope_of("STB-2026-56")


def test_the_other_records_of_a_treaty_by_key(store: GraphStore) -> None:
    _seed(store)
    treaty = resolve_instrument(store, "BWBV0009001")
    assert treaty is not None

    others = same_treaty(store, treaty)

    assert [o["key"] for o in others] == ["verdrag_1", "verdrag_2"]
    assert others[0] == {
        "key": "verdrag_1",
        "id": "instruments/verdrag_1",
        "type": "instrument",
        "labels": ["Verdragenbank"],
        "props": {"treaty_number": "001"},
    }
    verdrag = resolve_instrument(store, "verdrag_1")
    assert verdrag is not None
    assert [o["key"] for o in same_treaty(store, verdrag)] == [
        "bwbv0009001",
        "verdrag_2",
    ]
    assert same_treaty(store, {"key": "x", "props": {}}) == []
    assert same_treaty(store, {"key": "x", "props": {"treaty_number": 1}}) == []
    alone = resolve_instrument(store, "verdrag_3")
    assert alone is not None and same_treaty(store, alone) == []
