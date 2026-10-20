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

import datetime as dt
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RELATION_RELATED_TO
from lawgraph.db import EdgeWriter, GraphStore
from lawgraph.pipelines.semantic.rechtspraak_related import EDGE_SOURCE
from tests.integration.seed import write_judgments

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
    write_judgments(store, {ecli: _fixture(ecli) for ecli in ECLIS})
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


def _ids(store: GraphStore) -> dict[str, str]:
    return {r["ecli"]: r["id"] for r in store.query("SELECT ecli, id FROM judgments")}


def test_since_derives_the_judgments_fetched_since_as_a_run_over_all(
    store: GraphStore, cli: Any
) -> None:
    """With ``--since`` the judgments fetched since then get the edges a run over all gives
    them, and lose those it no longer gives; the edges of the others wait for that run."""
    full = _edges(store)
    ids = _ids(store)
    with EdgeWriter(store, what=None) as edges:
        for source, target in [
            ("ECLI:NL:HR:2026:1356", "ECLI:NL:PHR:2026:619"),
            ("ECLI:NL:RBROT:2022:12313", "ECLI:NL:PHR:2026:619"),
        ]:
            edges.add(ids[source], ids[target], RELATION_RELATED_TO, source=EDGE_SOURCE)
    store.execute(
        "DELETE FROM edges WHERE from_id = %(id)s AND to_id = %(to)s",
        {"id": ids["ECLI:NL:HR:2026:1356"], "to": ids["ECLI:NL:HR:2026:1357"]},
    )
    time.sleep(1.1)  # fetched_at has a precision of a second
    since = dt.datetime.now(dt.UTC).isoformat()
    # published again, changed (a run since then passes an unchanged one by)
    changed = _fixture("ECLI:NL:HR:2026:1356") + "\n"
    write_judgments(store, {"ECLI:NL:HR:2026:1356": changed})

    cli("semantic", "rechtspraak-related", "--since", since)

    assert set(_edges(store)) == set(full) | {
        ("ECLI:NL:RBROT:2022:12313", "ECLI:NL:PHR:2026:619")
    }


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
