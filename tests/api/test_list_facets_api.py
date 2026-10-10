"""``facets=false`` on the lists that count facets: the route asks the query for none and
answers ``facets`` null; without it the route asks for them, as before."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app

client = TestClient(app)

# the path of each list and the query its route asks
_LISTS = [
    ("/api/instruments", "instruments.get_instruments_list"),
    ("/api/dossiers", "dossiers.get_dossiers"),
    ("/api/decisions", "decisions.get_decisions"),
    ("/api/commitments", "government.get_commitments"),
]


def _answering(
    monkeypatch: pytest.MonkeyPatch, target: str, answer: dict[str, Any]
) -> list[dict[str, Any]]:
    """The options the route passes its query, which answers *answer*."""
    asked: list[dict[str, Any]] = []

    def fake(*args: Any, **options: Any) -> dict[str, Any]:
        asked.append(options)
        return answer

    monkeypatch.setattr(f"lawgraph.api.routes.{target}", fake)
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.enrich_dossier_docs", lambda store, docs: None
    )
    return asked


@pytest.mark.parametrize(("path", "target"), _LISTS)
def test_facets_false_asks_for_none_and_answers_null(
    monkeypatch: pytest.MonkeyPatch, path: str, target: str
) -> None:
    total = None if path == "/api/decisions" else 3
    asked = _answering(
        monkeypatch, target, {"total": total, "items": [], "facets": None}
    )
    response = client.get(path, params={"facets": "false"})
    assert response.status_code == 200
    assert response.json()["facets"] is None
    assert response.json()["total"] == total
    assert asked[0]["facets"] is False


@pytest.mark.parametrize(("path", "target"), _LISTS)
def test_facets_are_counted_by_default(
    monkeypatch: pytest.MonkeyPatch, path: str, target: str
) -> None:
    asked = _answering(monkeypatch, target, {"total": 0, "items": [], "facets": {}})
    response = client.get(path)
    assert response.status_code == 200
    assert isinstance(response.json()["facets"], dict)
    assert asked[0]["facets"] is True
