"""Tests for the stats API route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app

client = TestClient(app)

_STATS_DATA = {
    "nodes": {"instruments": 100, "judgments": 50},
    "stubs": {"judgments": 70},
    "edges": {"total": 200, "by_relation": {"AMENDS": 10}},
    "by_source": {"tk": {"publications": 30}},
    "instruments": {"by_kind": {}, "by_jurisdiction": {}},
}


def test_get_stats_returns_200(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.stats.get_db_stats",
        lambda store, keep: _STATS_DATA,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.stats.cached_data_as_of",
        lambda store: {
            "tk": {"retrieved_at": "2026-09-24T20:51:42Z", "newest": "2026-09-24"}
        },
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.stats.list_totals",
        lambda store: {"judgments": 50, "decisions": None},
    )
    response = client.get("/api/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["lists"] == {"judgments": 50, "decisions": None}
    assert "nodes" in body
    assert "edges" in body
    assert body["stubs"] == {"judgments": 70}
    assert body["data_as_of"]["tk"]["newest"] == "2026-09-24"


def _court(tier, code, count, first, last, source="rechtspraak"):
    return {
        "source": source,
        "tier": tier,
        "court_code": code,
        "court": code,
        "count": count,
        "first_date": first,
        "last_date": last,
    }


def test_coverage_counts_per_court_and_per_tier(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.stats.get_judgment_coverage",
        lambda store: {
            "courts": [
                _court("raad_van_state", "RVS", 40, "1984-02-24", "2026-09-23"),
                _court("gerechtshof", "GHAMS", 7, "2013-01-01", "2026-09-22"),
                _court("hoge_raad", "HR", 30, "1916-02-14", "2026-09-22"),
                _court("gerechtshof", "GHARL", 9, "2013-01-10", "2026-06-01"),
            ],
            "stubs": 18,
        },
    )
    body = client.get("/api/stats/coverage").json()

    assert (body["total"], body["stubs"]) == (86, 18)
    assert (body["first_date"], body["last_date"]) == ("1916-02-14", "2026-09-23")
    assert [(t["tier"], t["count"]) for t in body["tiers"]] == [
        ("hoge_raad", 30),
        ("raad_van_state", 40),
        ("gerechtshof", 16),
    ]
    gerechtshof = body["tiers"][2]
    assert (gerechtshof["first_date"], gerechtshof["last_date"]) == (
        "2013-01-01",
        "2026-09-22",
    )
    assert [c["court_code"] for c in body["courts"]] == ["RVS", "HR", "GHARL", "GHAMS"]


def _replaced(tier, code, count):
    return {"source": "rechtspraak", "tier": tier, "court_code": code, "count": count}


def test_coverage_counts_a_decision_published_twice_once(monkeypatch) -> None:
    """The publications another loaded one replaces are counted apart, as the list does."""
    monkeypatch.setattr(
        "lawgraph.api.routes.stats.get_judgment_coverage",
        lambda store: {
            "courts": [
                _court("hoge_raad", "HR", 30, "1916-02-14", "2026-09-22"),
                _court("andere_instantie", "XX", 2, "2000-06-27", "2000-06-27"),
            ],
            "stubs": 18,
            "replaced": [
                _replaced("hoge_raad", "HR", 3),
                _replaced("andere_instantie", "XX", 2),
            ],
        },
    )
    body = client.get("/api/stats/coverage").json()

    assert (body["total"], body["replaced"]) == (27, 5)
    assert [(c["court_code"], c["count"]) for c in body["courts"]] == [("HR", 27)]
    assert [t["tier"] for t in body["tiers"]] == ["hoge_raad"]
