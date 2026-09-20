"""API tests for the /api/annexes and instrument cross-law endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.config.constants import RELATION_SCOPED_BY

client = TestClient(app)

_ANNEX = {
    "_id": "annexes/bwbr0099999_annex_i",
    "_key": "bwbr0099999_annex_i",
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
    "_id": "articles/bwbr0099999_2",
    "_key": "bwbr0099999_2",
    "props": {
        "bwb_id": "BWBR0099999",
        "article_number": "2",
        "display_name": "Artikel 2",
    },
}

_OTHER_ARTICLE = {
    "_id": "articles/bwbr0088888_5",
    "_key": "bwbr0088888_5",
    "props": {
        "bwb_id": "BWBR0088888",
        "article_number": "5",
        "display_name": "Artikel 5",
    },
}

_SCOPE_EDGE = {
    "_key": "scope1",
    "relation": RELATION_SCOPED_BY,
    "meta": {"scope_type": "fixed"},
}


def test_annex_detail(monkeypatch):
    monkeypatch.setattr(
        "lawgraph.api.routes.annexes.get_annex",
        lambda store, key: _ANNEX if key == _ANNEX["_key"] else None,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.annexes.get_annex_referenced_by",
        lambda store, key: [
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
    monkeypatch.setattr(
        "lawgraph.api.routes.annexes.get_annex", lambda store, key: None
    )
    response = client.get("/api/annexes/unknown")
    assert response.status_code == 404


def test_annexes_list_shared_across_laws(monkeypatch):
    monkeypatch.setattr(
        "lawgraph.api.routes.annexes.list_annexes",
        lambda store, **kwargs: (
            [
                {
                    "annex": _ANNEX,
                    "referencing_laws": ["BWBR0099999", "BWBR0088888"],
                }
            ],
            1,
        ),
    )
    response = client.get("/api/annexes?shared_across_laws=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["annexes"][0]
    assert item["referencing_laws"] == ["BWBR0099999", "BWBR0088888"]


def test_cross_law_dependencies(monkeypatch):
    edge = {
        "_key": "x1",
        "semantic_type": "scope_limitation",
        "explanation": None,
        "confidence": 0.8,
    }
    monkeypatch.setattr(
        "lawgraph.api.routes.instruments.get_cross_law_dependencies",
        lambda store, bwb_id, limit: [
            {"edge": edge, "source_article": _ARTICLE, "target": _OTHER_ARTICLE}
        ],
    )
    response = client.get("/api/instruments/BWBR0099999/cross-law-dependencies")
    assert response.status_code == 200
    payload = response.json()
    assert payload["bwb_id"] == "BWBR0099999"
    dep = payload["dependencies"][0]
    assert dep["source_article"]["bwb_id"] == "BWBR0099999"
    assert dep["target_article"]["bwb_id"] == "BWBR0088888"
    assert dep["semantic_type"] == "scope_limitation"


def test_shared_annexes_for_law(monkeypatch):
    monkeypatch.setattr(
        "lawgraph.api.routes.instruments.get_shared_annexes_for_law",
        lambda store, bwb_id: [
            {
                "annex": _ANNEX,
                "referencing_laws": ["BWBR0099999", "BWBR0088888"],
            }
        ],
    )
    response = client.get("/api/instruments/BWBR0099999/shared-annexes")
    assert response.status_code == 200
    payload = response.json()
    assert payload["bwb_id"] == "BWBR0099999"
    assert payload["annexes"][0]["annex"]["display_name"] == "Vitale sectoren"
