"""The parliament endpoints: dossiers, committees, members, decisions, seats."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store

client = TestClient(app)

_DOSSIER = {
    "_id": "dossiers/36000",
    "_key": "36000",
    "labels": ["TK"],
    "props": {
        "number": "36000",
        "title": "Testwet",
        "title_source": "dossier",
        "current_stage": "wetsvoorstel",
        "stages_present": ["wetsvoorstel"],
        "track_kind": "wetsvoorstel",
        "closed": False,
        "opened_on": "2024-01-01",
        "closed_on": None,
    },
}

_COMMITTEE = {
    "_id": "committees/vws",
    "_key": "vws",
    "labels": ["TK"],
    "props": {
        "name": "Vaste commissie voor Volksgezondheid",
        "abbreviation": "VWS",
        "slug": "vws",
    },
    "active_dossier_count": 3,
}

_FACTION = {
    "_id": "factions/vvd",
    "_key": "vvd",
    "labels": ["TK"],
    "props": {
        "name": "Volkspartij voor Vrijheid en Democratie",
        "abbreviation": "VVD",
        "seats": 24,
        "active": True,
    },
    "member_count": 24,
}

_DECISION = {
    "id": "decisions/decision_b1",
    "key": "decision_b1",
    "date": "2024-10-16",
    "subject": "Motie over wachtlijsten",
    "external_id": "b-1",
    "dossier_numbers": ["36000"],
    "passed": True,
    "chamber": None,
    "vote_kind": "faction",
    "tally": {"Voor": 76, "Tegen": 74},
    "voters": {"Voor": 5, "Tegen": 6},
}


class _MockStore:
    """Answers nothing; every route under test has its query monkeypatched."""

    def get_node(self, collection: str, key: str):
        return None

    def query(self, aql: str, bind_vars: dict | None = None):
        return iter([])


@pytest.fixture(autouse=True)
def _mock_store():
    app.dependency_overrides[get_store] = lambda: _MockStore()
    yield
    app.dependency_overrides.pop(get_store, None)


# ── dossiers ─────────────────────────────────────────────────────────────────


def test_open_dossiers_are_wrapped_in_a_total_and_items(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_open_dossiers",
        lambda store, **kwargs: {"total": 1, "items": [_DOSSIER]},
    )
    body = client.get("/api/dossiers/open").json()
    assert body["total"] == 1
    assert body["items"][0]["number"] == "36000"
    assert body["items"][0]["title"] == "Testwet"
    assert body["items"][0]["current_stage"] == "wetsvoorstel"
    assert body["items"][0]["closed"] is False


def test_an_unknown_dossier_is_a_404(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_number",
        lambda store, number: None,
    )
    assert client.get("/api/dossiers/99999").status_code == 404


def test_a_dossier_reports_what_is_attached_to_it(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_number",
        lambda store, number: _DOSSIER,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.count_dossier_members",
        lambda store, dossier_id: {"documents": 4, "decisions": 2},
    )
    body = client.get("/api/dossiers/36000").json()
    assert body["number"] == "36000"
    assert body["document_count"] == 4
    assert body["decision_count"] == 2
    assert body["commitment_count"] == 0


def test_party_colors_are_served_under_parties() -> None:
    body = client.get("/api/parties/colors").json()
    assert body["colors"]["VVD"].startswith("#")


# ── committees, members, factions ────────────────────────────────────────────


def test_committees_are_listed_with_english_field_names(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_committees",
        lambda store: [_COMMITTEE],
    )
    body = client.get("/api/committees").json()
    assert body[0]["abbreviation"] == "VWS"
    assert body[0]["name"].startswith("Vaste commissie")
    assert body[0]["active_dossier_count"] == 3


def test_an_unknown_committee_is_a_404(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_committee_detail",
        lambda store, slug, **kwargs: None,
    )
    assert client.get("/api/committees/onbekend").status_code == 404


def test_members_are_listed_with_their_faction_timeline(monkeypatch) -> None:
    member = {
        "_id": "members/p1",
        "_key": "p1",
        "props": {
            "name": "Jan Jansen",
            "faction_memberships": [
                {
                    "faction_id": "factions/vvd",
                    "faction_key": "vvd",
                    "name": "VVD",
                    "abbreviation": "VVD",
                    "aliases": [],
                    "from_date": "2021-03-31",
                    "to_date": None,
                    "role": "Lid",
                }
            ],
        },
    }
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_members",
        lambda store, **kwargs: [member],
    )
    body = client.get("/api/members").json()
    assert body[0]["name"] == "Jan Jansen"
    assert body[0]["party"] == "VVD"
    assert body[0]["active"] is True
    assert body[0]["faction_memberships"][0]["from_date"] == "2021-03-31"


def test_an_unknown_member_is_a_404() -> None:
    assert client.get("/api/members/nobody").status_code == 404


def test_factions_are_listed_with_seats_and_member_count(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_factions",
        lambda store, **kwargs: [_FACTION],
    )
    body = client.get("/api/factions").json()
    assert body[0]["abbreviation"] == "VVD"
    assert body[0]["seats"] == 24
    assert body[0]["member_count"] == 24
    assert body[0]["active"] is True


# ── decisions ────────────────────────────────────────────────────────────────


def test_decisions_are_listed_with_their_tally(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decisions",
        lambda store, **kwargs: {"total": 1, "items": [_DECISION]},
    )
    body = client.get("/api/decisions").json()
    assert body["total"] == 1
    assert body["items"][0]["tally"] == {"Voor": 76, "Tegen": 74}
    assert body["items"][0]["vote_kind"] == "faction"


def test_a_decision_carries_every_vote_cast_on_it(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decision_detail",
        lambda store, key: {
            "_id": "decisions/decision_b1",
            "_key": "decision_b1",
            "props": {
                "date": "2024-10-16",
                "subject": "Motie",
                "decision_id": "b-1",
                "passed": True,
                "vote_kind": "faction",
                "tally": {"Voor": 76},
                "voters": {"Voor": 5},
            },
            "votes": [
                {
                    "voter_id": "factions/vvd",
                    "voter_key": "vvd",
                    "name": "VVD",
                    "choice": "Voor",
                    "seats": 24,
                }
            ],
        },
    )
    body = client.get("/api/decisions/decision_b1").json()
    assert body["passed"] is True
    assert body["votes"][0] == {
        "voter_id": "factions/vvd",
        "voter_key": "vvd",
        "name": "VVD",
        "choice": "Voor",
        "seats": 24,
    }


def test_an_unknown_decision_is_a_404(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decision_detail",
        lambda store, key: None,
    )
    assert client.get("/api/decisions/nothing").status_code == 404


# ── parliament ───────────────────────────────────────────────────────────────


def test_seats_are_reported_per_faction(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.parliament.get_factions",
        lambda store, **kwargs: [_FACTION],
    )
    body = client.get("/api/parliament/seats").json()
    assert body["total_seats"] == 150
    assert body["assigned_seats"] == 24
    assert body["factions"][0]["abbreviation"] == "VVD"
    assert body["factions"][0]["seats"] == 24
    assert body["factions"][0]["color"].startswith("#")
