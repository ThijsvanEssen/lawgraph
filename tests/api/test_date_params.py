"""A day a route reads is a day: every date parameter is ``format: date`` and 422 when it
is none, and a valid one reaches the query as an ISO string."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.db.queries.instruments import LawOnADate
from tests.api.stubs import stub_route
from tests.asserts import assert_status

client = TestClient(app)

# the names a route gives a day it filters or reads on
DATE_NAMES = {"from", "to", "since", "until", "due_before", "at_date", "date"}


def _date_params() -> list[tuple[str, str, str]]:
    """(path, place, name) of every date parameter of a GET route."""
    found = []
    for path, operations in app.openapi()["paths"].items():
        for parameter in (operations.get("get") or {}).get("parameters", []):
            name = parameter["name"]
            if name in DATE_NAMES or name.endswith(("_from", "_to")):
                found.append((path, parameter["in"], name))
    return found


def test_the_date_parameters_are_found() -> None:
    paths = {path for path, _, _ in _date_params()}
    assert {
        "/api/judgments",
        "/api/instruments/{bwb_id}/articles/at/{at_date}",
    } <= paths


@pytest.mark.parametrize(("path", "place", "name"), _date_params())
def test_a_date_parameter_is_a_day(path: str, place: str, name: str) -> None:
    operation = app.openapi()["paths"][path]["get"]
    (schema,) = [p["schema"] for p in operation["parameters"] if p["name"] == name]
    formats = {s.get("format") for s in schema.get("anyOf", [schema])}
    assert "date" in formats, f"{path} {name}: {schema}"


@pytest.mark.parametrize(("path", "place", "name"), _date_params())
def test_a_date_that_is_none_is_a_422(path: str, place: str, name: str) -> None:
    url = path.replace(f"{{{name}}}", "abc") if place == "path" else path
    url = url.replace("{bwb_id}", "BWBR0005289").replace("{key}", "k")
    params = {name: "abc"} if place == "query" else {}
    assert_status(client.get(url, params=params), 422)


def test_a_judgment_period_reaches_the_query_as_iso_days(monkeypatch) -> None:
    asked: list[Any] = []

    def fake(store: Any, filters: Any, **options: Any) -> dict[str, Any]:
        asked.append(filters)
        return {"items": [], "total": 0}

    stub_route(monkeypatch, "judgments", get_judgments_list=fake)
    response = client.get(
        "/api/judgments", params={"from": "2020-01-02", "to": "2021-03-04"}
    )
    assert_status(response, 200)
    assert (asked[0].from_date, asked[0].to_date) == ("2020-01-02", "2021-03-04")


def test_the_articles_on_a_day_read_it_as_an_iso_day(monkeypatch) -> None:
    asked: list[Any] = []

    def fake(store: Any, bwb_id: str, on: Any, **options: Any) -> LawOnADate:
        asked.append(on)
        return LawOnADate([], 0, None)

    stub_route(monkeypatch, "instruments", get_articles_at=fake)
    response = client.get("/api/instruments/BWBR0005289/articles/at/2020-01-02")
    assert_status(response, 200)
    assert asked == ["2020-01-02"]
    assert response.json()["at_date"] == "2020-01-02"


def test_the_feed_periods_read_their_days_as_the_feed_does(monkeypatch) -> None:
    asked: list[Any] = []

    def fake(store: Any, filters: Any, per: str) -> dict[str, Any]:
        asked.append(filters)
        return {"periods": [], "written_at": None}

    monkeypatch.setattr("lawgraph.api.routes.feed.feed_events.get_periods", fake)
    stub_route(monkeypatch, "feed", _data_as_of={})
    response = client.get(
        "/api/feed/periods",
        params={"since": "2020-01-02", "until": "2020-01-31", "per": "day"},
    )
    assert response.status_code == 200, response.text
    assert (asked[0].since, asked[0].until) == ("2020-01-02", "2020-01-31")
    assert response.json()["since"] == "2020-01-02"


def test_the_feed_periods_count_by_month_or_day_alone(monkeypatch) -> None:
    stub_route(monkeypatch, "feed", _data_as_of={})
    response = client.get("/api/feed/periods", params={"per": "week"})
    assert_status(response, 422)
