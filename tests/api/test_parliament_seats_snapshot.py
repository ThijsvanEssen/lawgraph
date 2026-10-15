"""``/api/parliament/seats`` of the Tweede Kamer, the Eerste Kamer and the Eerste Kamer on a
day, answered exactly as pinned in ``parliament_seats.json``: the order of the hall (a
faction the plan does not place at the right end), vacant seats, no coalition without a
cabinet, a faction of the past without a key, the hall from the day it was read, and a 404
before the first known seats of the Eerste Kamer."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.db.queries.coalition import Coalition

client = TestClient(app)
PINNED = pathlib.Path(__file__).with_name("parliament_seats.json")
ROUTE = "lawgraph.api.routes.parliament"


def _faction(key: str, abbreviation: str, seats: int, **props: Any) -> dict[str, Any]:
    return {
        "id": f"factions/{key}",
        "key": key,
        "props": {"abbreviation": abbreviation, "name": f"Partij {abbreviation}",
                  "seats": seats, **props},
    }  # fmt: skip


TK = [
    _faction("vvd", "VVD", 24),
    _faction("nieuw", "NIEUW", 2),
    _faction("sp", "SP", 5),
]
EK = [
    _faction(
        "ek_vvd", "VVD", 10, retrieved_on="2026-06-01T10:00:00", data_since="2003"
    ),
    _faction("ek_sp", "SP", 3, retrieved_on="2026-05-01", data_since="2007"),
    _faction("ek_leeg", "LEEG", 0, retrieved_on="2026-06-01"),
]
EK_MEMBERS = [
    {"key": "m1", "props": {"ek": {"seat": {"block": "right", "row": 1, "column": 2},
                                    "faction": "ek_vvd", "abbreviation": "VVD",
                                    "name": "A. Lid"}}},
    {"key": "m2", "props": {"ek": {"seat": {"block": "chair", "row": 0, "column": 0},
                                    "faction": "ek_sp", "name": "B. Voorzitter"}}},
    {"key": "m3", "props": {"ek": {}}},
]  # fmt: skip
STRETCH = {
    "from_date": "2023-06-13",
    "seats": {"VVD": 10, "OUD": 4, "SP": 3, "NUL": 0},
    "source": {"kiesraad": {"read_on": "2023-06-01"}},
    "checked": True,
}


@pytest.fixture(autouse=True)
def parliament(monkeypatch: pytest.MonkeyPatch) -> None:
    def factions(store: Any, *, active: bool | None = None, chamber: str = "TK") -> Any:
        return EK if chamber == "EK" else TK

    def coalition(store: Any, day: str) -> Coalition:
        if day < "2010-01-01":
            return Coalition(cabinet=None)
        return Coalition(
            cabinet={"key": "k", "name": "kabinet-K"}, factions={"vvd", "ek_vvd"}
        )

    monkeypatch.setattr(f"{ROUTE}.get_factions", factions)
    monkeypatch.setattr(f"{ROUTE}.coalition_of_day", coalition)
    monkeypatch.setattr(
        f"{ROUTE}.get_seats_on", lambda store, day: {"vvd": 30, "sp": 1}
    )
    monkeypatch.setattr(
        f"{ROUTE}.vacancies_between",
        lambda store, start, end: [
            {"faction_key": "nieuw", "from_date": "2000-01-01", "to_date": "2030-01-01"}
        ],
    )
    monkeypatch.setattr(f"{ROUTE}.get_ek_members", lambda store, **kw: EK_MEMBERS)
    monkeypatch.setattr(
        f"{ROUTE}.ek_seats.stretch_on",
        lambda store, day: STRETCH if day >= "2003-06-10" else None,
    )


REQUESTS = {
    "tk": {},
    "tk on a day": {"date": "2009-05-05"},
    "ek": {"chamber": "EK"},
    "ek on a day before the hall was read": {"chamber": "EK", "date": "2024-01-01"},
    "ek on a day after the hall was read": {"chamber": "EK", "date": "2026-07-01"},
}


def _answers() -> dict[str, Any]:
    answers = {}
    for name, params in REQUESTS.items():
        response = client.get("/api/parliament/seats", params=params)
        assert response.status_code == 200, response.text
        answers[name] = response.json()
    return answers


def test_the_seats_are_answered_as_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    import datetime as dt

    class Today(dt.date):
        @classmethod
        def today(cls) -> Today:
            return cls(2026, 7, 1)

    monkeypatch.setattr(f"{ROUTE}.dt.date", Today)
    assert _answers() == json.loads(PINNED.read_text())


def test_the_eerste_kamer_has_no_seats_before_2003() -> None:
    response = client.get(
        "/api/parliament/seats", params={"chamber": "EK", "date": "2002-01-01"}
    )
    assert response.status_code == 404
