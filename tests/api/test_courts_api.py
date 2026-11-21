"""``GET /api/courts/districts``: the court map of a year, newest by default, 404 without
one."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.routes import courts
from tests.asserts import assert_status

client = TestClient(app)


def _row(year: int, code: str, check: str | None) -> dict[str, Any]:
    return {
        "year": year,
        "municipality_code": code,
        "municipality": "Den Helder",
        "province": "Noord-Holland",
        "district": "Noord-Holland",
        "district_code": "AR01",
        "circuit": "Gerechtshof Amsterdam",
        "circuit_code": "RT11",
        "district_article": "4",
        "circuit_article": "14",
        "law_district": None,
        "district_check": check,
        "circuit_check": "agrees" if check else None,
    }


@pytest.fixture()
def table(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    asked: list[int] = []

    def districts_of(store: object, year: int) -> list[dict[str, Any]]:
        asked.append(year)
        return [_row(year, "GM0400", "not_in_text" if year == 2026 else None)]

    monkeypatch.setattr(courts, "years", lambda store: [2026, 2025])
    monkeypatch.setattr(courts, "districts_of", districts_of)
    return asked


def test_the_newest_year_by_default_with_its_gaps(table: list[int]) -> None:
    answer = client.get("/api/courts/districts")
    assert_status(answer, 200)
    body = answer.json()
    assert (body["year"], body["years"], body["checked"]) == (2026, [2026, 2025], True)
    (item,) = body["items"]
    assert item["district"] == {
        "code": "AR01",
        "name": "Noord-Holland",
        "article_number": "4",
    }
    assert item["district_check"] == "not_in_text" and item["law_district"] is None


def test_an_older_year_is_not_checked(table: list[int]) -> None:
    body = client.get("/api/courts/districts?year=2025").json()
    assert table == [2025]
    assert body["checked"] is False and body["items"][0]["district_check"] is None


@pytest.mark.usefixtures("table")
def test_a_year_without_a_map_is_404() -> None:
    assert_status(client.get("/api/courts/districts?year=2020"), 404)
    assert_status(client.get("/api/courts/districts?year=1990"), 422)


def test_no_map_at_all_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(courts, "years", lambda store: [])
    assert_status(client.get("/api/courts/districts"), 404)
