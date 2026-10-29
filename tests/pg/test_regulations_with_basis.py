"""The regulations ``semantic bwb-grondslagen`` reads, on the test server: the BWB
regulations whose node states a basis, not one with an empty basis or of another source."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    SOURCE_BWB,
)
from lawgraph.core.models import NodeType
from lawgraph.db import GraphStore
from lawgraph.db.queries.semantic import bwb as semantic_bwb

BASIS = [{"doc": "jci1.3:c:BWBR0001947&artikel=125", "bwb_id": "BWBR0001947"}]


def _regulation(key: str, source: str, **props: Any) -> dict[str, Any]:
    return {
        "key": key,
        "type": NodeType.INSTRUMENT.value,
        "labels": [],
        "props": {"source": source, "bwb_id": key.upper(), **props},
    }


def test_only_the_regulations_that_state_a_basis_are_read(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [
            _regulation("bwbr0001950", SOURCE_BWB, basis=BASIS),
            _regulation("bwbr0000001", SOURCE_BWB, basis=[]),
            _regulation("bwbr0000002", SOURCE_BWB),
            _regulation("bwbr0000003", "eurlex", basis=BASIS),
        ],
    )

    rows = list(semantic_bwb.regulations_with_basis(store))

    assert rows == [
        {
            "key": "bwbr0001950",
            "bwb_id": "BWBR0001950",
            "basis": BASIS,
            "basis_preamble": None,
            "basis_unresolved": None,
        }
    ]


def test_a_law_named_only_in_words_counts_as_a_basis(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [
            _regulation(
                "bwbr0008498",
                SOURCE_BWB,
                basis=[],
                basis_preamble="Gelet op artikel 1;",
            ),
            _regulation("bwbr0000001", SOURCE_BWB, basis=[], basis_preamble=""),
        ],
    )

    rows = list(semantic_bwb.regulations_with_basis(store))

    assert [r["key"] for r in rows] == ["bwbr0008498"]


def test_a_gap_kept_is_read_to_be_cleared(store: GraphStore) -> None:
    gap = [{"bwb_id": "BWBR0001840", "article": "86", "text": "86", "reason": "x"}]
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS,
        [_regulation("bwbr0002335", SOURCE_BWB, basis=[], basis_unresolved=gap)],
    )

    rows = list(semantic_bwb.regulations_with_basis(store))

    assert [(r["key"], r["basis_unresolved"]) for r in rows] == [("bwbr0002335", gap)]


def _version(key: str, valid_from: str | None) -> dict[str, Any]:
    bwb_id = key.split("_")[0].upper()
    return {
        "key": key,
        "type": NodeType.INSTRUMENT_VERSION.value,
        "labels": [],
        "props": {"bwb_id": bwb_id, "valid_from": valid_from},
    }


def test_the_first_toestand_of_a_law(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENT_VERSIONS,
        [
            _version("bwbr0001840_2002_03_21", "2002-03-21"),
            _version("bwbr0001840_2023_02_22", "2023-02-22"),
            _version("bwbr0000002_a", "2010-01-01"),
            _version("bwbr0000002_b", None),  # a toestand without a start: unknown
            _version("bwbr0000003_a", "2001-01-01"),  # not asked for
        ],
    )

    rows = list(semantic_bwb.first_versions(store, ["BWBR0001840", "BWBR0000002"]))

    assert [(r["bwb_id"], r["first_from"]) for r in rows] == [
        ("BWBR0000002", None),
        ("BWBR0001840", "2002-03-21"),
    ]
