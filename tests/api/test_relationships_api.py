"""API tests for the /api/relationships endpoints and article relationships view."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.config.constants import RELATION_SCOPED_BY

client = TestClient(app)


_SOURCE_ARTICLE = {
    "_id": "articles/bwbr0001854_287",
    "_key": "bwbr0001854_287",
    "props": {
        "bwb_id": "BWBR0001854",
        "article_number": "287",
        "display_name": "Artikel 287",
    },
}

_TARGET_ARTICLE = {
    "_id": "articles/bwbr0001854_24c",
    "_key": "bwbr0001854_24c",
    "props": {
        "bwb_id": "BWBR0001854",
        "article_number": "24c",
        "display_name": "Artikel 24c",
    },
}

_EDGE = {
    "_key": "abc123",
    "_from": _SOURCE_ARTICLE["_id"],
    "_to": _TARGET_ARTICLE["_id"],
    "relation": "REFERS_TO_ARTICLE",
    "semantic_type": "definitional_reference",
    "explanation": "Patroon 'als bedoeld in' direct vóór de verwijzing",
    "confidence": 0.92,
}

_ANNEX = {
    "_id": "annexes/bwbr0001854_annex_i",
    "_key": "bwbr0001854_annex_i",
    "props": {
        "bwb_id": "BWBR0001854",
        "label": "I",
        "display_name": "Vitale sectoren",
        "entries": [
            {"index": 0, "name": "Telecommunicatie"},
            {"index": 1, "name": "Energie"},
        ],
    },
}

_SCOPE_EDGE = {
    "_key": "scope1",
    "_from": _SOURCE_ARTICLE["_id"],
    "_to": _ANNEX["_id"],
    "relation": RELATION_SCOPED_BY,
    "meta": {"scope_type": "discretionary"},
}


def test_relationship_types_endpoint():
    response = client.get("/api/relationships/types")
    assert response.status_code == 200
    payload = response.json()
    assert "definitional_reference" in payload["semantic_types"]
    assert payload == {"semantic_types": sorted(payload["semantic_types"])}
    assert len(payload["semantic_types"]) == 7


def test_article_relationships_endpoint(monkeypatch):
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_relationship_data",
        lambda store, article_id: {
            "upstream": [
                {"edge": _EDGE, "target": _TARGET_ARTICLE, "instrument": None}
            ],
            "downstream": [],
            "scope": [{"edge": _SCOPE_EDGE, "annex": _ANNEX}],
        },
    )
    response = client.get("/api/articles/BWBR0001854/287/relationships")
    assert response.status_code == 200
    payload = response.json()

    assert payload["article_id"] == _SOURCE_ARTICLE["_id"]
    upstream = payload["upstream_dependencies"]
    assert len(upstream) == 1
    rel = upstream[0]
    assert rel["semantic_type"] == "definitional_reference"
    assert rel["target_article"]["article_number"] == "24c"
    assert rel["explanation"].startswith("Patroon")
    assert payload["downstream_implications"] == []

    scope = payload["scope_articles"]
    assert len(scope) == 1
    assert scope[0]["scope_type"] == "discretionary"
    assert scope[0]["annex_entries"] == ["Telecommunicatie", "Energie"]


def test_relationships_search(monkeypatch):
    monkeypatch.setattr(
        "lawgraph.api.routes.relationships.search_relationships",
        lambda store, **kwargs: (
            [
                {
                    "edge": _EDGE,
                    "source_article": _SOURCE_ARTICLE,
                    "target": _TARGET_ARTICLE,
                }
            ],
            1,
        ),
    )
    response = client.get(
        "/api/relationships/search?type=definitional_reference&law=BWBR0001854"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    rel = payload["relationships"][0]
    assert rel["edge_id"] == "abc123"
    assert rel["semantic_type"] == "definitional_reference"
    assert rel["source_article"]["article_number"] == "287"
    assert rel["target_article"]["article_number"] == "24c"


def test_relationships_search_rejects_unknown_type():
    response = client.get("/api/relationships/search?type=not_a_type")
    assert response.status_code == 422
