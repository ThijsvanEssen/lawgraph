"""The reads of ``lawgraph check`` on a real PostgreSQL."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import (
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_TK_ZAAK,
    SOURCE_ECHR,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, raw_source_doc
from lawgraph.db.queries import checks as check_queries
from tests.pg.plans import explain, plan_nodes, recorded


def _instrument(key: str, **props: object) -> dict[str, object]:
    return {"key": key, "type": "instrument", "labels": [], "props": props}


def test_counts_of_nodes_and_derived_props(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _instrument(
                "a", source="bwb", basis=[], celex_refs=[], implements_celex=[]
            ),
            _instrument("b", source="bwb", basis=None, stub=False),
            _instrument("c", source="bwb", stub=True),
            _instrument("t1", source="bwb", kind="verdrag", treaty_number="001"),
            _instrument("t2", source="bwb", kind="verdrag", treaty_number="002"),
            _instrument("t3", source="bwb", kind="verdrag"),
            _instrument("v1", source="verdragenbank", treaty_number="001"),
        ],
    )
    assert check_queries.count_nodes_of_source(store, "instruments", "bwb") == 6
    # b, t1, t2, t3: no stub, not every derived prop
    assert check_queries.count_regulations_without_derived_props(store) == 4
    assert check_queries.bwb_treaties_by_match(store) == {
        "matched": 1,
        "unmatched": 1,
        "unnumbered": 1,
    }


def test_nodes_of_a_source_count_on_its_column(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Judgments and documents have a column ``source``: the count reads an index on it,
    never the props (a judgment's props hold its text), and counts what the props say."""
    for collection, kind in (("judgments", "judgment"), ("documents", "document")):
        store.bulk_insert_or_update_nodes(
            collection,
            [
                {"key": "a", "type": kind, "labels": [], "props": {"source": "x"}},
                {"key": "b", "type": kind, "labels": [], "props": {"source": "x"}},
                {"key": "c", "type": kind, "labels": [], "props": {"source": "y"}},
                {"key": "d", "type": kind, "labels": [], "props": {}},
            ],
        )
        assert check_queries.count_nodes_of_source(store, collection, "x") == 2
        calls = recorded(store, monkeypatch)
        check_queries.count_nodes_of_source(store, collection, "y")
        (call,) = calls
        assert "props" not in call.text
        plan = explain(store, call.statement, call.params, disable=["seqscan"])
        scans = {node["Node Type"] for node in plan_nodes(plan)}
        assert "Seq Scan" not in scans
        monkeypatch.undo()


def test_dangling_edges_and_cases(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            {
                "key": "1",
                "type": "case",
                "labels": [],
                "props": {"dossier_numbers": ["1"]},
            },
            {"key": "2", "type": "case", "labels": [], "props": {}},
        ],
    )
    edge = {"relation": "PART_OF", "source": "tk", "status": "canoniek", "meta": {}}
    store.bulk_insert_or_update_edges(
        [
            {"key": "e1", "from_id": "cases/1", "to_id": "cases/2", **edge},
            {"key": "e2", "from_id": "cases/1", "to_id": "dossiers/9", **edge},
        ]
    )
    assert list(check_queries.dangling_edges(store)) == [
        {"relation": "PART_OF", "n": 1}
    ]
    assert check_queries.cases_by_named_dossier(store) == {False: 1, True: 1}


def test_echr_judgments_per_ecli(store: GraphStore) -> None:
    def record(item: str, ecli: str | None) -> dict[str, object]:
        return raw_source_doc(
            source=SOURCE_ECHR,
            kind=RAW_KIND_ECHR_JUDGMENT,
            external_id=item,
            payload_json={"ecli": ecli},
        )

    store.insert_raw_sources(
        [
            record("1", "ecli:ce:echr:1"),
            record("2", " ECLI:CE:ECHR:1"),
            record("3", None),
        ]
    )
    assert check_queries.count_echr_judgments_in_raw(store) == 2


def test_tk_cases_in_raw_leave_out_the_deleted_and_those_without_an_id(
    store: GraphStore,
) -> None:
    def record(key: str, payload: dict[str, object]) -> dict[str, object]:
        return raw_source_doc(
            source=SOURCE_TK,
            kind=RAW_KIND_TK_ZAAK,
            external_id=key,
            payload_json=payload,
        )

    store.insert_raw_sources(
        [
            record("1", {"Id": "z1", "Soort": "Motie"}),
            record("2", {"Id": "z2", "Verwijderd": False}),
            record("3", {"Id": "z3", "Verwijderd": True}),  # the Kamer deleted it
            record("4", {"Id": "z4", "Verwijderd": "true"}),  # not the boolean: a case
            record("5", {"Id": " ", "Soort": "Motie"}),  # no id: no case
            record("6", {"ZaakNummer": "2026Z01234"}),
        ]
    )
    assert check_queries.count_tk_cases_in_raw(store) == 4
