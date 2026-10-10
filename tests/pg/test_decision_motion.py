"""The motion or amendment a decision was taken on (``motion`` of ``/api/decisions``): the
oldest paper of the case the vote singled out, as its dictum; the Kamerstuk a vote of the
Eerste Kamer on a motion is about; none for anything else."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {"_key": key, "_from": source, "_to": target, "relation": relation,
            "source": "test"}  # fmt: skip


def _graph(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("kst_36800_12", "document", kind="Motie", date="2026-09-01",
                  dossier_number="36800", sequence=12),
            # the motion changed: a later paper of the same case
            _node("kst_36800_19", "document", kind="Gewijzigde motie",
                  date="2026-09-05", dossier_number="36800", sequence=19),
            _node("kst_36800_8", "document", kind="Amendement", date="2026-08-20",
                  dossier_number="36800", sequence=8),
            _node("kst_36800_ab", "document", kind="Motie", date="2026-07-01",
                  dossier_number="36800", number="AB"),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_nodes(
        "cases",
        [
            _node("z_m", "case", external_id="Z-M", kind="Motie"),
            _node("z_a", "case", external_id="Z-A", kind="Amendement"),
            _node("z_leeg", "case", external_id="Z-LEEG", kind="Motie"),
            _node("z_w", "case", external_id="Z-W", kind="Wetgeving"),
        ],
    )
    decision = {"date": "2026-09-08", "dossier_numbers": ["36800"], "passed": True}
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node("s_motie", "decision", primary_case_id="Z-M",
                  primary_case_kind="Motie", **decision),
            _node("s_amendement", "decision", primary_case_id="Z-A",
                  primary_case_kind="Amendement", **decision),
            # a motion whose case has no paper (yet)
            _node("s_leeg", "decision", primary_case_id="Z-LEEG",
                  primary_case_kind="Motie", **decision),
            # the bill itself: no motion
            _node("s_wet", "decision", primary_case_id="Z-W",
                  primary_case_kind="Wetgeving", **decision),
            # the Eerste Kamer on a motion: about its Kamerstuk
            _node("ek_2026_07_07_36800_ab", "decision", kind="Motie", chamber="EK",
                  date="2026-07-07", result="aangenomen", dossier_numbers=["36800"]),
        ],
    )  # fmt: skip
    store.bulk_insert_or_update_edges(
        [
            _edge("p1", "documents/kst_36800_12", "cases/z_m", "PART_OF"),
            _edge("p2", "documents/kst_36800_19", "cases/z_m", "PART_OF"),
            _edge("p3", "documents/kst_36800_8", "cases/z_a", "PART_OF"),
            _edge("a1", "decisions/s_motie", "cases/z_m", "ABOUT"),
            _edge("a2", "decisions/s_amendement", "cases/z_a", "ABOUT"),
            _edge("a3", "decisions/s_leeg", "cases/z_leeg", "ABOUT"),
            _edge("a4", "decisions/s_wet", "cases/z_w", "ABOUT"),
            _edge("a5", "decisions/ek_2026_07_07_36800_ab", "documents/kst_36800_ab",
                  "ABOUT"),
        ]
    )  # fmt: skip


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    _graph(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


EXPECTED = {
    # the oldest paper of the case, not the changed motion after it
    "s_motie": {
        "collection": "documents",
        "key": "kst_36800_12",
        "path": "/kamerstukken/36800/12",
    },
    "s_amendement": {
        "collection": "documents",
        "key": "kst_36800_8",
        "path": "/kamerstukken/36800/8",
    },
    "s_leeg": None,
    "s_wet": None,
    "ek_2026_07_07_36800_ab": {
        "collection": "documents",
        "key": "kst_36800_ab",
        "path": "/kamerstukken/36800/AB",
    },
}


def test_each_decision_in_the_list_names_its_motion(client: TestClient) -> None:
    items = client.get("/api/decisions", params={"unvoted": "true"}).json()["items"]
    assert {i["key"]: i["motion"] for i in items} == EXPECTED


@pytest.mark.parametrize("key", list(EXPECTED))
def test_the_detail_names_its_motion(client: TestClient, key: str) -> None:
    assert client.get(f"/api/decisions/{key}").json()["motion"] == EXPECTED[key]
