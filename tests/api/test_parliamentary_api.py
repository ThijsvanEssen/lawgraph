"""Tests for parliamentary API routes: dossiers, commissies, stemmingen."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store

client = TestClient(app)

# ---------------------------------------------------------------------------
# Minimal fixture documents
# ---------------------------------------------------------------------------

_DOSSIER_DOC = {
    "_id": "dossiers/36000",
    "_key": "36000",
    "labels": ["Dossier"],
    "props": {
        "kamerstuknummer": "36000",
        "titel": "Testwet",
        "huidige_fase": "wetsvoorstel",
        "afgedaan": False,
        "geopend_op": "2024-01-01",
        "gesloten_op": None,
    },
}

_COMMISSIE_DOC = {
    "_id": "commissies/vws",
    "_key": "vws",
    "labels": ["Commissie"],
    "props": {
        "naam": "Commissie Volksgezondheid",
        "afkorting": "VWS",
        "slug": "vws",
    },
    "active_dossier_count": 3,
}


# ---------------------------------------------------------------------------
# MockStore — provides the minimum surface used by commissies/leden routes
# ---------------------------------------------------------------------------


class _MockStore:
    def get_node(self, collection: str, key: str):
        return None

    def query(self, aql: str, bind_vars: dict | None = None):
        return iter([])


app.dependency_overrides[get_store] = lambda: _MockStore()


# ---------------------------------------------------------------------------
# Dossier tests
# ---------------------------------------------------------------------------


def test_list_open_dossiers_returns_200(monkeypatch):
    """GET /api/dossiers/open returns 200 and a non-empty list."""
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_open_dossiers",
        lambda store, **kwargs: [_DOSSIER_DOC],
    )
    response = client.get("/api/dossiers/open")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1


def test_get_dossier_detail_returns_404_for_unknown(monkeypatch):
    """GET /api/dossiers/{nummer} returns 404 when dossier is not found."""
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_nummer",
        lambda store, nummer: None,
    )
    response = client.get("/api/dossiers/99999")
    assert response.status_code == 404


def test_get_dossier_detail_returns_200(monkeypatch):
    """GET /api/dossiers/{nummer} returns 200 and response contains kamerstuknummer."""
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_nummer",
        lambda store, nummer: _DOSSIER_DOC,
    )
    # _count_members uses store.query; the MockStore already returns an empty iter
    # which causes rows[0] to fail — patch _count_members directly instead.
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers._count_members",
        lambda store, dossier_id, collection: 0,
    )
    response = client.get("/api/dossiers/36000")
    assert response.status_code == 200
    body = response.json()
    assert body["kamerstuknummer"] == "36000"


# ---------------------------------------------------------------------------
# Commissie tests
# ---------------------------------------------------------------------------


def test_list_commissies_returns_200(monkeypatch):
    """GET /api/commissies returns 200 and a list."""
    monkeypatch.setattr(
        "lawgraph.api.routes.commissies.get_all_commissies",
        lambda store: [_COMMISSIE_DOC],
    )
    response = client.get("/api/commissies")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1


def test_get_commissie_detail_returns_404_for_unknown(monkeypatch):
    """GET /api/commissies/{slug} returns 404 when commissie is not found."""
    monkeypatch.setattr(
        "lawgraph.api.routes.commissies.get_commissie_detail",
        lambda store, slug: None,
    )
    response = client.get("/api/commissies/onbekend")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Stemmingen tests
# ---------------------------------------------------------------------------


def test_list_stemmingen_returns_200(monkeypatch):
    """GET /api/stemmingen returns 200 and a dict with items."""
    monkeypatch.setattr(
        "lawgraph.api.routes.stemmingen.get_stemmingen",
        lambda store, **kwargs: {"items": [], "total": 0},
    )
    response = client.get("/api/stemmingen")
    assert response.status_code == 200
    body = response.json()
    assert "total" in body
