"""Judgments in the feed (BE-26) on a real PostgreSQL: on the day they were published, of
the highest courts and the Parket unless a ``tier`` is asked for, through ``GET /api/feed``
and its summary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.settings import API_ALLOWED_ORIGINS
from lawgraph.db import GraphStore


def _judgment(key: str, tier: str, published_on: str | None, **props: Any) -> dict:
    return {
        "_key": key,
        "type": "judgment",
        "labels": ["Rechtspraak"],
        "props": {
            "ecli": key.upper().replace("_", ":"),
            "display_name": f"Uitspraak {key}",
            "tier": tier,
            "court_code": tier[:2].upper(),
            "date_eff": "2026-08-01",
            "published_on": published_on,
            "summary": f"Inhoudsindicatie {key}.",
            "source": "rechtspraak",
            "decision_kind": "arrest",
            "judgment_metadata": {"type": "Cassatie"},
            "text": "De tekst, die het item niet leest.",
            **props,
        },
    }


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _judgment("ecli_nl_hr_2026_1", "hoge_raad", "2026-09-03"),
            _judgment("ecli_nl_rvs_2026_2", "raad_van_state", "2026-09-02"),
            _judgment(
                "ecli_nl_phr_2026_3",
                "parket",
                "2026-09-01",
                decision_kind="conclusie",
                advocate_general="T. Hartlief",
                advocate_general_role="advocaat-generaal",
            ),
            # not in the feed by default: a court of first instance
            _judgment("ecli_nl_rbams_2026_4", "rechtbank", "2026-09-04"),
            # never: without a publication, a stub, a publication another replaces
            _judgment("ecli_nl_hr_2026_5", "hoge_raad", None),
            _judgment("ecli_nl_hr_2026_6", "hoge_raad", "2026-09-05", stub=True),
            _judgment(
                "ecli_nl_hr_2026_7",
                "hoge_raad",
                "2026-09-05",
                same_as="ECLI:NL:HR:2026:1",
            ),
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app, headers={"Origin": API_ALLOWED_ORIGINS[0]})
    finally:
        app.dependency_overrides.pop(get_store, None)


def _feed(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/feed", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(answer: dict[str, Any]) -> list[str]:
    return [item["id"] for item in answer["items"]]


DEFAULT = [
    "judgments/ecli_nl_hr_2026_1",
    "judgments/ecli_nl_rvs_2026_2",
    "judgments/ecli_nl_phr_2026_3",
]


@pytest.mark.parametrize("facets", [True, False])
def test_the_highest_courts_by_the_day_they_were_published(
    client: TestClient, facets: bool
) -> None:
    answer = _feed(client, facets=str(facets).lower())
    assert _ids(answer) == DEFAULT
    item = answer["items"][0]
    assert (item["kind"], item["date"], item["title"], item["summary"]) == (
        "uitspraak",
        "2026-09-03",
        "Uitspraak ecli_nl_hr_2026_1",
        "Inhoudsindicatie ecli_nl_hr_2026_1.",
    )
    assert item["judgment"] == {
        "ecli": "ECLI:NL:HR:2026:1",
        "court": "HO",
        "tier": "hoge_raad",
        "court_kind": None,
        "decision_kind": "arrest",
        "procedure": "Cassatie",
        "decided_on": "2026-08-01",
        "advocate_general": None,
        "advocate_general_role": None,
    }
    assert item["official_url"] == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2026:1"
    )
    conclusion = answer["items"][2]["judgment"]
    assert (conclusion["advocate_general"], conclusion["advocate_general_role"]) == (
        "T. Hartlief",
        "advocaat-generaal",
    )
    if facets:
        assert answer["total"] == 3
        assert {f["value"]: f["count"] for f in answer["facets"]["kind"]} == {
            "uitspraak": 3
        }


@pytest.mark.parametrize("facets", [True, False])
def test_a_tier_keeps_the_judgments_of_that_tier(
    client: TestClient, facets: bool
) -> None:
    flag = str(facets).lower()
    assert _ids(_feed(client, tier="rechtbank", facets=flag)) == [
        "judgments/ecli_nl_rbams_2026_4"
    ]
    both = _feed(client, tier="rechtbank,parket", facets=flag)
    assert _ids(both) == [
        "judgments/ecli_nl_rbams_2026_4",
        "judgments/ecli_nl_phr_2026_3",
    ]
    # a chamber is no court's: none
    assert _ids(_feed(client, chamber="TK", facets=flag)) == []


def test_pages_of_judgments_neither_repeat_nor_skip(client: TestClient) -> None:
    seen: list[str] = []
    params: dict[str, Any] = {"limit": 1, "facets": "false"}
    while True:
        answer = _feed(client, **params)
        seen += _ids(answer)
        if not answer.get("next_cursor"):
            break
        params["cursor"] = answer["next_cursor"]
    assert seen == DEFAULT


def test_an_unknown_tier_is_422(client: TestClient) -> None:
    assert client.get("/api/feed", params={"tier": "nope"}).status_code == 422


def test_a_summary_counts_the_judgments_and_shows_none_one_by_one(
    client: TestClient,
) -> None:
    summary = client.get(
        "/api/feed/summary", params={"until": "2026-09-03", "days": 3}
    ).json()
    days = {day["date"]: day for day in summary["days"]}
    assert {k["value"]: k["count"] for k in days["2026-09-03"]["kinds"]} == {
        "uitspraak": 1
    }
    assert summary["items"] == []
