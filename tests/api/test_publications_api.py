"""Tests for the publications API route."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store

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


class _MockStoreList:
    def query(self, aql, bind_vars=None):
        return [_PUB_ROW]


class _MockStoreNotFound:
    class _publications:
        @staticmethod
        def get(key):
            return None

    publications = _publications()


class _MockStoreFound:
    class _publications:
        @staticmethod
        def get(key):
            return _PUB_DOC

    publications = _publications()


@pytest.fixture
def client_with_store(fake_store):
    app.dependency_overrides[get_store] = lambda: fake_store
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


@pytest.fixture
def fake_store():
    return _MockStoreList()


@pytest.fixture
def fake_store_not_found():
    return _MockStoreNotFound()


@pytest.fixture
def fake_store_found():
    return _MockStoreFound()


@pytest.fixture
def client_with_store_not_found(fake_store_not_found):
    app.dependency_overrides[get_store] = lambda: fake_store_not_found
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


@pytest.fixture
def client_with_store_found(fake_store_found):
    app.dependency_overrides[get_store] = lambda: fake_store_found
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


def test_list_publications_returns_200(client_with_store) -> None:
    response = client_with_store.get("/api/publications")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 0


def test_get_publication_text_returns_404_for_unknown(
    client_with_store_not_found,
) -> None:
    response = client_with_store_not_found.get("/api/publications/nonexistent-key")
    assert response.status_code == 404


def test_get_publication_text_returns_200_for_known(
    client_with_store_found,
) -> None:
    response = client_with_store_found.get("/api/publications/abc123")
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "abc123"
    assert body["title"] == "Memorie van Toelichting"
