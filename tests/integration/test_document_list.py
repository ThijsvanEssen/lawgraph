"""The list of the papers of the chambers (``GET /api/documents``), on a real database."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_DOCUMENTS
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter


def _paper(key: str, labels: list[str], **props: Any) -> Node:
    return Node(
        collection=COLLECTION_DOCUMENTS,
        type=NodeType.DOCUMENT,
        key=key,
        labels=labels,
        props=props,
    )


PAPERS = [
    _paper(
        "mvt",
        ["TK", "Kamerstuk"],
        kind="Memorie van toelichting",
        title="Wet toekomstbestendige huurcommissie",
        date="2025-06-25",
        sequence=3,
        dossier_number="36791",
        dossier_numbers=["36791"],
        session_year="2024-2025",
    ),
    _paper(
        "motion",
        ["TK", "Kamerstuk"],
        kind="Motie",
        title="Motie over huur",
        date="2026-02-01",
        sequence=12,
        dossier_number="36791",
        dossier_numbers=["36791"],
        session_year="2025-2026",
    ),
    _paper(
        "ek_c",
        ["EersteKamer", "EK"],
        kind="Memorie van antwoord",
        title="Wet toekomstbestendige huurcommissie; Memorie van antwoord",
        date="2026-09-01",
        number="C",
        dossier_number="36791",
        dossier_numbers=["36791"],
        session_year="2025-2026",
    ),
    # neither chamber: a publication in the Staatsblad is no paper of a chamber
    _paper("stb", ["Staatsblad"], kind="Staatsblad", date="2026-09-20", title="Wet"),
    _paper(
        "other",
        ["TK", "Kamerstuk"],
        kind="Brief regering",
        title="Brief",
        date="2026-03-01",
        sequence=1,
        dossier_number="36000",
        dossier_numbers=["36000"],
    ),
]


def _get(client: TestClient, **params: Any) -> Any:
    response = client.get("/api/documents", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_papers_of_the_chambers_are_listed_counted_and_numbered(
    database: str,
) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(PAPERS)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        everything = _get(client)
        dossier = _get(client, dossier="36791")
        senate = _get(client, dossier="36791", chamber="EK")
        motions = _get(client, kind="Motie")
        window = _get(client, **{"from": "2026-01-01", "to": "2026-06-30"})
        page = _get(client, limit=1, facets="false")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert everything["total"] == 4  # not the Staatsblad
    assert [d["key"] for d in everything["items"]] == ["ek_c", "other", "motion", "mvt"]
    assert [d["key"] for d in dossier["items"]] == ["ek_c", "motion", "mvt"]
    ek = senate["items"][0]
    assert (ek["chamber"], ek["number"], ek["dossier_number"], ek["session_year"]) == (
        "EK",
        "C",
        "36791",
        "2025-2026",
    )
    mvt = dossier["items"][-1]
    assert (mvt["chamber"], mvt["number"]) == ("TK", "3")
    # each facet is counted without its own filter
    assert {f["value"]: f["count"] for f in senate["facets"]["chamber"]} == {
        "EK": 1,
        "TK": 2,
    }
    assert {f["value"]: f["count"] for f in senate["facets"]["kind"]} == {
        "Memorie van antwoord": 1
    }
    assert [d["key"] for d in motions["items"]] == ["motion"]
    assert {f["value"] for f in motions["facets"]["kind"]} == {
        "Memorie van toelichting",
        "Motie",
        "Memorie van antwoord",
        "Brief regering",
    }
    assert [d["key"] for d in window["items"]] == ["other", "motion"]
    assert (page["total"], page["facets"], len(page["items"])) == (None, None, 1)
