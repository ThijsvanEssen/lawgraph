"""The regulations ``semantic bwb-grondslagen`` reads, on the test server: the BWB
regulations whose node states a basis, not one with an empty basis or of another source."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_INSTRUMENTS, SOURCE_BWB
from lawgraph.core.models import NodeType
from lawgraph.db import GraphStore
from lawgraph.db.queries.semantic import bwb as semantic_bwb

BASIS = [{"doc": "jci1.3:c:BWBR0001947&artikel=125", "bwb_id": "BWBR0001947"}]


def _regulation(key: str, source: str, **props: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "type": NodeType.INSTRUMENT.value,
        "labels": [],
        "props": {"source": source, "bwb_id": key.upper(), **props},
    }


def test_only_the_regulations_that_state_a_basis_are_read(database: str) -> None:
    store = GraphStore()
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

    assert rows == [{"key": "bwbr0001950", "bwb_id": "BWBR0001950", "basis": BASIS}]
