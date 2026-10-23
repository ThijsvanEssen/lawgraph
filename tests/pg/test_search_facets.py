"""The full search counts its hits per type and divides them (``facets=true``), and pages
through them (``offset``): the judgments by tier and year, the papers by kind, the laws by
whether they hold, over every hit that holds the words, not the page."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search import counts, dispatch
from tests.databases import Api

TIERS = ["hoge_raad", "gerechtshof", "rechtbank"]


def _nodes(store: GraphStore, collection: str, rows: list[dict[str, Any]]) -> None:
    store.bulk_insert_or_update_nodes(
        collection,
        [
            {
                "key": r.pop("key"),
                "type": collection.rstrip("s"),
                "labels": [],
                "props": r,
            }
            for r in rows
        ],
    )


@pytest.fixture()
def store(store: GraphStore, monkeypatch: pytest.MonkeyPatch) -> GraphStore:
    monkeypatch.setattr(dispatch, "LIVE_BUDGET", 30.0)
    version_cache.clear()
    _nodes(
        store,
        "judgments",
        [
            {
                "key": f"j{n}",
                "ecli": f"ECLI:NL:XX:{2018 + n % 4}:{n}",
                "tier": TIERS[n % 3],
                "date_eff": f"{2018 + n % 4}-03-01",
                "display_name": f"Uitspraak {n}",
                "summary": "Een geschil over de huurovereenkomst.",
            }
            for n in range(12)
        ],
    )
    _nodes(
        store,
        "documents",
        [
            {
                "key": f"d{n}",
                "kind": "motie" if n % 3 else "brief",
                "title": f"Motie huurovereenkomst {n}",
                "display_name": f"Motie huurovereenkomst {n}",
                "date": "2025-01-01",
            }
            for n in range(5)
        ],
    )
    _nodes(
        store,
        "instruments",
        [
            {
                "key": "huur_old",
                "bwb_id": "BWBR0000001",
                "title": "Huurwet oud",
                "date_expired": "2000-01-01",
            },
            {"key": "huur_new", "bwb_id": "BWBR0000002", "title": "Huurwet nieuw"},
        ],
    )
    return store


def _search(api: Api, **params: Any) -> dict[str, Any]:
    answer: dict[str, Any] = api.get_json(
        "/api/search", q="huurovereenkomst", types=["judgments"], **params
    )
    return answer


def test_the_totals_and_facets_are_over_every_hit_not_the_page(api: Api) -> None:
    answer = _search(api, limit=5, facets="true")
    assert len(answer["results"]["judgments"]) == 5
    assert answer["counts"]["judgments"] == {"total": 12, "capped": False}
    facets = answer["facets"]["judgments"]
    assert {f["value"]: f["count"] for f in facets["tier"]} == {
        "hoge_raad": 4,
        "gerechtshof": 4,
        "rechtbank": 4,
    }
    # the newest year first
    assert [(f["value"], f["count"]) for f in facets["year"]] == [
        ("2021", 3),
        ("2020", 3),
        ("2019", 3),
        ("2018", 3),
    ]


def test_without_facets_nothing_is_counted(api: Api) -> None:
    answer = _search(api)
    assert (answer["counts"], answer["facets"], answer["offset"]) == (None, None, 0)


def test_pages_follow_each_other(api: Api) -> None:
    first = [h["id"] for h in _search(api, limit=5)["results"]["judgments"]]
    second = _search(api, limit=5, offset=5)
    ids = [h["id"] for h in second["results"]["judgments"]]
    last = [h["id"] for h in _search(api, limit=5, offset=10)["results"]["judgments"]]
    assert second["offset"] == 5
    assert len(set(first + ids + last)) == 12
    assert (len(first), len(ids), len(last)) == (5, 5, 2)
    everything = [h["id"] for h in _search(api, limit=20)["results"]["judgments"]]
    assert first + ids + last == everything


def test_a_period_narrows_the_count_and_its_facets(api: Api) -> None:
    answer = _search(api, facets="true", **{"from": "2020-01-01"})
    assert answer["counts"]["judgments"]["total"] == 6
    assert [f["value"] for f in answer["facets"]["judgments"]["year"]] == [
        "2021",
        "2020",
    ]


def test_the_count_stops_at_its_cap(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(counts, "COUNT_CAP", 7)
    answer = _search(api, limit=5, facets="true")
    assert answer["counts"]["judgments"] == {"total": 7, "capped": True}


def test_papers_by_kind_and_laws_by_validity(api: Api) -> None:
    answer = api.get_json(
        "/api/search", q="motie", types=["documents", "members"], facets="true"
    )
    assert answer["counts"]["documents"] == {"total": 5, "capped": False}
    assert {f["value"]: f["count"] for f in answer["facets"]["documents"]["kind"]} == {
        "motie": 3,
        "brief": 2,
    }
    # a type that is not counted
    assert answer["counts"]["members"] == {"total": 0, "capped": False}
    assert "members" not in answer["facets"]

    laws = api.get_json(
        "/api/search", q="huurwet", types=["instruments"], facets="true"
    )
    assert laws["counts"]["instruments"]["total"] == 2
    assert {
        f["value"]: f["count"] for f in laws["facets"]["instruments"]["validity"]
    } == {
        "in_force": 1,
        "expired": 1,
    }


def test_typing_has_no_offset_or_facets(api: Api) -> None:
    for extra in ({"offset": 1}, {"facets": "true"}):
        response = api.get("/api/search", params={"q": "huur", "mode": "live", **extra})
        assert response.status_code == 422, (extra, response.text)


def test_a_type_without_a_count_has_the_hits_it_found(api: Api) -> None:
    answer = api.get_json(
        "/api/search", q="huur", types=["members"], facets="true", offset=3
    )
    assert answer["counts"]["members"] == {"total": 0, "capped": False}
