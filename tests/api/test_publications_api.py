"""Tests for the publications API route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app

client = TestClient(app)

_PUB_ROW = {
    "key": "abc123",
    "title": "Memorie van Toelichting",
    "soort": "Memorie van toelichting",
    "datum": "2024-03-01",
    "external_id": "some-uuid",
    "source": "tk",
    "has_text": True,
    "linked_articles": 3,
}

_PUB_DOC = {
    "_id": "publications/abc123",
    "_key": "abc123",
    "labels": ["TK"],
    "props": {
        "title": "Memorie van Toelichting",
        "soort": "Memorie van toelichting",
        "datum": "2024-03-01",
        "external_id": "some-uuid",
        "source": "tk",
        "text": "De inhoud van het stuk...",
    },
}


def test_list_publications_returns_200() -> None:
    from lawgraph.api.dependencies import get_store

    class _MockStore:
        def query(self, aql, bind_vars=None):
            return [_PUB_ROW]

    app.dependency_overrides[get_store] = lambda: _MockStore()
    try:
        response = client.get("/api/publications")
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] >= 0
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_get_publication_text_returns_404_for_unknown() -> None:
    from lawgraph.api.dependencies import get_store

    class _MockStore:
        class _publications:
            @staticmethod
            def get(key):
                return None

        publications = _publications()

    app.dependency_overrides[get_store] = lambda: _MockStore()
    try:
        response = client.get("/api/publications/nonexistent-key")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_get_publication_text_returns_200_for_known(monkeypatch) -> None:
    from lawgraph.api.dependencies import get_store

    class _MockStore:
        class _publications:
            @staticmethod
            def get(key):
                return _PUB_DOC

        publications = _publications()

    app.dependency_overrides[get_store] = lambda: _MockStore()
    try:
        response = client.get("/api/publications/abc123")
        assert response.status_code == 200
        body = response.json()
        assert body["key"] == "abc123"
        assert body["title"] == "Memorie van Toelichting"
    finally:
        app.dependency_overrides.pop(get_store, None)
