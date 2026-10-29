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
from lawgraph.db import GraphStore
from tests.asserts import assert_status


def _judgment(key: str, tier: str, published_on: str | None, **props: Any) -> dict:
    return {
        "key": key,
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
            # a judgment of the Court of Justice, cited with its case number
            _judgment(
                "ecli_eu_c_2026_8",
                "hvj_eu",
                "2026-09-06",
                court="Hof van Justitie van de Europese Unie",
                case_number="C-160/20",
                source="cjeu",
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
        yield TestClient(app)
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
def test_a_feed_that_asks_for_no_kind_has_the_judgments_of_the_highest_courts(
    client: TestClient, facets: bool
) -> None:
    answer = _feed(client, facets=str(facets).lower())
    assert _ids(answer) == DEFAULT
    if facets:  # the total and the kind facet count what the page holds
        assert answer["total"] == 3
        assert {f["value"]: f["count"] for f in answer["facets"]["kind"]} == {
            "uitspraak": 3
        }


def test_a_kind_without_judgments_leaves_them_out(client: TestClient) -> None:
    answer = _feed(client, kind="Motie")
    assert _ids(answer) == []
    assert answer["total"] == 0


def test_the_atom_feed_has_the_judgments(client: TestClient) -> None:
    response = client.get("/api/feed.atom")
    assert response.status_code == 200, response.text
    assert "Uitspraak ecli_nl_hr_2026_1" in response.text


def test_a_summary_without_a_kind_counts_the_judgments(client: TestClient) -> None:
    summary = client.get(
        "/api/feed/summary", params={"until": "2026-09-03", "days": 3}
    ).json()
    days = {day["date"]: day for day in summary["days"]}
    assert {k["value"]: k["count"] for k in days["2026-09-03"]["kinds"]} == {
        "uitspraak": 1
    }


@pytest.mark.parametrize("facets", [True, False])
def test_the_highest_courts_by_the_day_they_were_published(
    client: TestClient, facets: bool
) -> None:
    answer = _feed(client, kind="uitspraak", facets=str(facets).lower())
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
        "outcome": None,
        "outcome_text": None,
        "conclusion_outcome": None,
        "conclusion_outcome_text": None,
        "echr_findings": [],
        "path": "/uitspraken/ECLI:NL:HR:2026:1",
        "cite": {
            "short": "HR 1 augustus 2026",
            "full": "HR 1 augustus 2026, ECLI:NL:HR:2026:1",
        },
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
    params: dict[str, Any] = {"limit": 1, "facets": "false", "kind": "uitspraak"}
    while True:
        answer = _feed(client, **params)
        seen += _ids(answer)
        if not answer.get("next_cursor"):
            break
        params["cursor"] = answer["next_cursor"]
    assert seen == DEFAULT


def test_the_atom_title_names_the_tiers_in_words(client: TestClient) -> None:
    atom = client.get("/api/feed.atom", params={"tier": "hoge_raad,parket"})
    assert "<title>Concordans: hoge raad en parket</title>" in atom.text


def test_an_unknown_tier_is_422(client: TestClient) -> None:
    assert_status(client.get("/api/feed", params={"tier": "nope"}), 422)


def test_a_summary_counts_the_judgments_and_shows_none_one_by_one(
    client: TestClient,
) -> None:
    summary = client.get(
        "/api/feed/summary",
        params={"until": "2026-09-03", "days": 3, "kind": "uitspraak"},
    ).json()
    days = {day["date"]: day for day in summary["days"]}
    assert {k["value"]: k["count"] for k in days["2026-09-03"]["kinds"]} == {
        "uitspraak": 1
    }
    assert summary["items"] == []


def test_a_judgment_of_the_court_of_justice_is_cited_with_its_case_number(
    client: TestClient,
) -> None:
    (item,) = _feed(client, tier="hvj_eu", facets="false")["items"]
    assert item["judgment"]["cite"]["short"] == "HvJ EU 1 augustus 2026, C-160/20"


# The lower courts (B14): on 2026-09-04 a gerechtshof in two areas, a rechtbank in one and
# the rechtbank of the fixture in none; on 2026-09-03 a tuchtcollege. Neither the court
# outside the Netherlands nor the Hoge Raad is a lower court.
LOWER = [
    _judgment(
        "ecli_nl_ghams_2026_10",
        "gerechtshof",
        "2026-09-04",
        subjects=["Civiel recht; Verbintenissenrecht", "Bestuursrecht; Belastingrecht"],
    ),
    _judgment(
        "ecli_nl_rbrot_2026_11", "rechtbank", "2026-09-04", subjects=["Strafrecht"]
    ),
    _judgment(
        "ecli_nl_tadra_2026_12",
        "tuchtcollege",
        "2026-09-03",
        subjects=["Civiel recht; Beroepsaansprakelijkheid", "Civiel recht"],
    ),
    _judgment(
        "ecli_xx_2026_13",
        "buitenlandse_instantie",
        "2026-09-04",
        subjects=["Strafrecht"],
    ),
    _judgment("ecli_nl_hr_2026_14", "hoge_raad", "2026-09-04", subjects=["Strafrecht"]),
]


@pytest.fixture()
def lower(client: TestClient, store: GraphStore) -> TestClient:
    store.bulk_insert_or_update_nodes("judgments", LOWER)
    return client


def _summary(client: TestClient, **params: Any) -> dict[str, dict[str, Any]]:
    response = client.get(
        "/api/feed/summary", params={"until": "2026-09-04", "days": 3, **params}
    )
    assert response.status_code == 200, response.text
    return {day["date"]: day for day in response.json()["days"]}


def test_a_summary_counts_the_lower_courts_per_area_of_law(lower: TestClient) -> None:
    days = _summary(lower, lower_courts="true")
    assert days["2026-09-04"]["lower_courts"] == {
        "total": 3,
        "subject_areas": [
            {"value": "Bestuursrecht", "count": 1},
            {"value": "Civiel recht", "count": 1},
            {"value": "Strafrecht", "count": 1},
            {"value": None, "count": 1},
        ],
    }
    # an area once per judgment, however many of its subjects are in it
    assert days["2026-09-03"]["lower_courts"] == {
        "total": 1,
        "subject_areas": [{"value": "Civiel recht", "count": 1}],
    }
    assert days["2026-09-02"]["lower_courts"] == {"total": 0, "subject_areas": []}
    # the day's own counts are those of the feed: the highest courts alone
    assert days["2026-09-04"]["total"] == 1


def test_a_summary_without_lower_courts_has_none(lower: TestClient) -> None:
    days = _summary(lower)
    assert not any("lower_courts" in day for day in days.values())


def test_the_lower_courts_follow_the_filters(lower: TestClient) -> None:
    days = _summary(lower, lower_courts="true", tier="gerechtshof,hoge_raad")
    assert days["2026-09-04"]["lower_courts"]["total"] == 1
    motions = _summary(lower, lower_courts="true", kind="Motie")
    assert motions["2026-09-04"]["lower_courts"] == {"total": 0, "subject_areas": []}


@pytest.mark.parametrize("facets", [True, False])
def test_an_area_of_law_keeps_the_judgments_in_it(
    lower: TestClient, facets: bool
) -> None:
    day = {"since": "2026-09-04", "until": "2026-09-04", "facets": str(facets).lower()}
    tiers = "gerechtshof,rechtbank,tuchtcollege"
    civil = _feed(lower, tier=tiers, subject_area="Civiel recht", **day)
    assert _ids(civil) == ["judgments/ecli_nl_ghams_2026_10"]
    if facets:
        assert civil["total"] == 1
    # ``none``: the judgments without an area of law
    assert _ids(_feed(lower, tier=tiers, subject_area="none", **day)) == [
        "judgments/ecli_nl_rbams_2026_4"
    ]
    # without a tier, those of the highest courts
    assert _ids(_feed(lower, subject_area="Strafrecht", **day)) == [
        "judgments/ecli_nl_hr_2026_14"
    ]
    assert _ids(_feed(lower, kind="Motie", subject_area="Strafrecht", **day)) == []


def test_an_area_of_law_is_not_counted_per_period(client: TestClient) -> None:
    assert_status(
        client.get("/api/feed/periods", params={"subject_area": "Strafrecht"}), 422
    )
