"""The dossier of a regulation is that of the bill that enacted it, on trimmed real XML of the
Awb (BWBR0005537). The real ``normalize bwb`` and ``semantic bwb-amendments``, then the API.

The intitule of the Awb names Stb. 1992, 315 of dossier 21221; its ``<wetgeving>`` names
Stb. 2012, 682 of dossier 32450, the last change to the structure of the law. The Awb is
``LEGISLATED_IN`` 21221, and a run removes the edge to 32450 an earlier run derived, but not
an edge another pipeline made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND,
    RELATION_LEGISLATED_IN,
)
from lawgraph.core.models import Node
from lawgraph.db import (
    EdgeWriter,
    GraphStore,
    NodeWriter,
)
from lawgraph.pipelines.semantic.bwb_amendments import EDGE_SOURCE
from tests.integration.seed import write_toestanden

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LAW = "BWBR0005537"
AWB = f"{COLLECTION_INSTRUMENTS}/bwbr0005537"
ENACTED, RESTRUCTURED, OTHER = "21221", "32450", "36000"


def _seed(store: GraphStore) -> None:
    write_toestanden(
        store,
        [
            (
                RAW_KIND_BWB_TOESTAND,
                LAW,
                (FIXTURES / "bwb_awb_annexes_toestand.xml").read_text(),
                {
                    "bwb_id": LAW,
                    "start_date": "2026-08-15",
                    "end_date": "9999-12-31",
                },
            )
        ],
    )
    with NodeWriter(store) as nodes:
        nodes.add_all(
            Node(
                collection=COLLECTION_DOSSIERS,
                key=number,
                labels=[],
                props={"number": number, "label": number, "title": f"Dossier {number}"},
            )
            for number in (ENACTED, RESTRUCTURED, OTHER)
        )


def _legislated_in(store: GraphStore) -> set[tuple[str, str]]:
    statement = f"""
    SELECT to_id, source FROM {COLLECTION_EDGES}
    WHERE from_id = %(awb)s AND relation = %(relation)s
    """
    rows = store.query(statement, {"awb": AWB, "relation": RELATION_LEGISLATED_IN})
    return {(row["to_id"], row["source"]) for row in rows}


def test_a_regulation_is_legislated_in_the_dossier_that_enacted_it(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    cli("normalize", "bwb")
    # what an earlier run derived from the last structural change, and an edge of another
    # pipeline
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            AWB,
            f"{COLLECTION_DOSSIERS}/{RESTRUCTURED}",
            RELATION_LEGISLATED_IN,
            source=EDGE_SOURCE,
        )
        edges.add(
            AWB, f"{COLLECTION_DOSSIERS}/{OTHER}", RELATION_LEGISLATED_IN, source="t"
        )

    cli("semantic", "bwb-amendments")

    assert _legislated_in(store) == {
        (f"{COLLECTION_DOSSIERS}/{ENACTED}", EDGE_SOURCE),
        (f"{COLLECTION_DOSSIERS}/{OTHER}", "t"),
    }
    app.dependency_overrides[get_store] = lambda: store
    try:
        awb = TestClient(app).get(f"/api/instruments/{LAW}").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert awb["dossier_numbers"] == [ENACTED]
