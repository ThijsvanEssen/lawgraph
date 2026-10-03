"""RELATED_TO between judgments, from the summary, on five real judgments: the real
``normalize rechtspraak`` and ``semantic rechtspraak-related``, then the API.

- ECLI:NL:HR:2026:1356 says "Samenhang met 24/01299", the case number of
  ECLI:NL:HR:2026:1357, which says "Samenhang met 24/01260" back. ECLI:NL:PHR:2026:619 is the
  conclusion in case 24/01299, of another court (the Parket): no edge to it.
- ECLI:NL:RBROT:2022:12313 says "Zie ook ECLI:NL:RBROT:2022:10632 (einduitspraak) en
  ECLI:NL:RVS:2026:2737 (uitspraak in hoger beroep)": an edge to the first, none to the
  second, which is not in the graph.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ECLIS = [
    "ECLI:NL:HR:2026:1356",
    "ECLI:NL:HR:2026:1357",
    "ECLI:NL:PHR:2026:619",
    "ECLI:NL:RBROT:2022:12313",
    "ECLI:NL:RBROT:2022:10632",
]


def _fixture(ecli: str) -> str:
    name = "rechtspraak_" + ecli.split(":", 2)[2].replace(":", "_").lower() + ".xml"
    return (FIXTURES / name).read_text()


def _edges(store: GraphStore) -> dict[tuple[str, str], dict[str, Any]]:
    statement = """
    SELECT f.props ->> 'ecli' AS source, t.props ->> 'ecli' AS target, e.doc -> 'meta' AS meta
    FROM edges e JOIN judgments f ON f.id = e.from_id JOIN judgments t ON t.id = e.to_id
    WHERE e.relation = 'RELATED_TO' AND e.from_collection = 'judgments'
    """
    return {(r["source"], r["target"]): r["meta"] for r in store.query(statement)}


@pytest.fixture()
def store(database: str, cli: Any) -> GraphStore:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for ecli in ECLIS:
            writer.add(
                raw_source_doc(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=_fixture(ecli),
                    meta={"ecli": ecli},
                )
            )
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak-related")
    return store


def test_connected_cases_by_case_number_and_by_ecli(store: GraphStore) -> None:
    edges = _edges(store)
    assert set(edges) == {
        ("ECLI:NL:HR:2026:1356", "ECLI:NL:HR:2026:1357"),
        ("ECLI:NL:HR:2026:1357", "ECLI:NL:HR:2026:1356"),
        ("ECLI:NL:RBROT:2022:12313", "ECLI:NL:RBROT:2022:10632"),
    }
    assert edges[("ECLI:NL:HR:2026:1356", "ECLI:NL:HR:2026:1357")] == {
        "basis": "summary_text",
        "text": "Samenhang met 24/01299.",
    }
    # the conclusion of another court with the same case number gets no edge
    assert not any(target == "ECLI:NL:PHR:2026:619" for _, target in edges)


def test_a_second_run_changes_nothing(store: GraphStore, cli: Any) -> None:
    before = _edges(store)
    cli("semantic", "rechtspraak-related")
    assert _edges(store) == before


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_detail_lists_the_connected_cases_both_ways(client: TestClient) -> None:
    body = client.get("/api/judgments/ECLI:NL:RBROT:2022:10632").json()
    assert [j["ecli"] for j in body["related_to"]] == ["ECLI:NL:RBROT:2022:12313"]
    body = client.get("/api/judgments/ECLI:NL:PHR:2026:619").json()
    assert body["related_to"] == []
