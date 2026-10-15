"""API tests for the /api/annexes endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.config.constants import RELATION_SCOPED_BY
from tests.api.stubs import stub_route

client = TestClient(app)

_ANNEX = {
    "id": "annexes/bwbr0099999_annex_i",
    "key": "bwbr0099999_annex_i",
    "props": {
        "bwb_id": "BWBR0099999",
        "label": "I",
        "display_name": "Vitale sectoren",
        "title": "Vitale sectoren",
        "entries": [
            {"index": 0, "name": "Telecommunicatie"},
            {"index": 1, "name": "Energie"},
        ],
    },
}

_ARTICLE = {
    "id": "articles/bwbr0099999_2",
    "key": "bwbr0099999_2",
    "props": {
        "bwb_id": "BWBR0099999",
        "article_number": "2",
        "display_name": "Artikel 2",
    },
}

_OTHER_ARTICLE = {
    "id": "articles/bwbr0088888_5",
    "key": "bwbr0088888_5",
    "props": {
        "bwb_id": "BWBR0088888",
        "article_number": "5",
        "display_name": "Artikel 5",
    },
}

_SCOPE_EDGE = {
    "key": "scope1",
    "relation": RELATION_SCOPED_BY,
    "meta": {"scope_type": "fixed"},
}


def test_annex_detail(monkeypatch):
    stub_route(
        monkeypatch,
        "annexes",
        get_annex=lambda store, key: _ANNEX if key == _ANNEX["key"] else None,
        get_annex_referenced_by=[
            {"edge": _SCOPE_EDGE, "article": _ARTICLE},
            {"edge": _SCOPE_EDGE, "article": _OTHER_ARTICLE},
        ],
    )
    response = client.get("/api/annexes/bwbr0099999_annex_i")
    assert response.status_code == 200
    payload = response.json()
    assert payload["annex"]["label"] == "I"
    assert [e["name"] for e in payload["annex"]["entries"]] == [
        "Telecommunicatie",
        "Energie",
    ]
    referenced = payload["referenced_by"]
    assert len(referenced) == 2
    assert referenced[1]["article"]["bwb_id"] == "BWBR0088888"
    assert referenced[0]["scope_type"] == "fixed"


def test_annex_detail_404(monkeypatch):
    stub_route(monkeypatch, "annexes", get_annex=None)
    response = client.get("/api/annexes/unknown")
    assert response.status_code == 404
