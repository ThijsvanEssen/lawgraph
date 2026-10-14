"""Only a missing node is a 404: any other error after it loaded is a 500."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db.queries.not_found import NotFound

client = TestClient(app, raise_server_exceptions=False)


def _raise(exc: Exception) -> Any:
    def fake(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return fake


# (the query the route calls, a URL of that route)
_ROUTES = [
    (
        "lawgraph.api.routes.judgments.get_judgment_with_relations",
        "/api/judgments/ECLI:NL:HR:2020:1",
    ),
    (
        "lawgraph.api.routes.articles.get_article_with_relations",
        "/api/articles/BWBR0001854/287",
    ),
    (
        "lawgraph.api.routes.articles.get_article_history",
        "/api/articles/BWBR0001854/287/history",
    ),
    (
        "lawgraph.api.routes.nodes.get_node_with_neighbors",
        "/api/nodes/instruments/BWBR0001854",
    ),
]


@pytest.mark.parametrize(("query", "url"), _ROUTES)
def test_a_value_error_after_loading_is_a_500(monkeypatch, query, url):
    monkeypatch.setattr(query, _raise(ValueError("a mapping went wrong")))
    assert client.get(url).status_code == 500


@pytest.mark.parametrize(("query", "url"), _ROUTES)
def test_a_missing_node_is_a_404(monkeypatch, query, url):
    monkeypatch.setattr(query, _raise(NotFound("Node", "x")))
    response = client.get(url)
    assert response.status_code == 404
    assert response.json() == {"detail": "Node 'x' not found."}


class _EmptyStore:
    """Holds no node."""

    def get_document(self, collection: str, key: str) -> None:
        return None

    def has_node(self, collection: str, key: str) -> bool:
        return False


# the queries that answer None for what is not there
_NONE_QUERIES = [
    "activities.get_activity",
    "annexes.get_annex",
    "committees.get_committee_activities",
    "committees.get_committee_detail",
    "decisions.get_decision_detail",
    "documents.get_document",
    "dossiers.get_dossier_by_number",
    "government.get_cabinet",
    "government.get_commitment",
    "instruments.resolve_instrument",
]

_DETAIL_URLS = [
    "/api/activities/x",
    "/api/activities/x/records",
    "/api/annexes/x",
    "/api/articles/BWBR0001854/287/cited-by",
    "/api/articles/BWBR0001854/287/delegated",
    "/api/cabinets/x",
    "/api/cabinets/x/seats",
    "/api/commitments/x",
    "/api/committees/x",
    "/api/committees/x/activities",
    "/api/decisions/x",
    "/api/decisions/x/document",
    "/api/documents/x",
    "/api/documents/x/passages?bwb_id=BWBR0001854&article=287",
    "/api/dossiers/36000",
    "/api/dossiers/36000/documents",
    "/api/factions/x",
    "/api/factions/x/dossiers",
    "/api/factions/x/votes",
    "/api/factions/x/touched-instruments",
    "/api/instruments/BWBR0001854",
    "/api/instruments/BWBR0001854/definitions",
    "/api/instruments/BWBR0001854/eu-links",
    "/api/members/x",
    "/api/members/x/votes",
    "/api/members/x/dossiers",
    "/api/members/x/touched-instruments",
    "/api/paths?ids=judgments/x,articles/y",
]


@pytest.mark.parametrize("url", _DETAIL_URLS)
def test_a_detail_route_answers_404_for_what_is_not_there(monkeypatch, url):
    for query in _NONE_QUERIES:
        monkeypatch.setattr(f"lawgraph.api.routes.{query}", lambda *a, **k: None)
    monkeypatch.setitem(app.dependency_overrides, get_store, _EmptyStore)
    assert client.get(url).status_code == 404
