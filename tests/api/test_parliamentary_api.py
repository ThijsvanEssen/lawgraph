"""The parliament endpoints: dossiers, committees, members, decisions, seats."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db.queries.decisions import DecisionFilters

client = TestClient(app)

_DOSSIER = {
    "_id": "dossiers/36000",
    "_key": "36000",
    "labels": ["TK"],
    "props": {
        "number": "36000",
        "label": "36000",
        "title": "Testwet",
        "title_source": "dossier",
        "kind": "Wetgeving",
        "kind_basis": "case",
        "phases": [{"name": "Voorstel van wet", "done": True, "date": "2024-01-01"}],
        "current_phase": "Voorstel van wet",
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
        "active_dossier_count": 3,
    },
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
    "kind": "Motie",
    "decision_kind": "Stemmen - aangenomen",
    "passed": True,
    "chamber": None,
    "vote_kind": "faction",
    "tally": {"Voor": 76, "Tegen": 74},
    "voters": {"Voor": 5, "Tegen": 6},
}


class _MockStore:
    """Knows no node; every route under test has its query functions monkeypatched."""

    def get_node(self, collection: str, key: str):
        return None


@pytest.fixture(autouse=True)
def _mock_store():
    app.dependency_overrides[get_store] = lambda: _MockStore()
    yield
    app.dependency_overrides.pop(get_store, None)


# ── dossiers ─────────────────────────────────────────────────────────────────


def test_open_dossiers_are_wrapped_in_a_total_and_items(monkeypatch) -> None:
    asked = []

    def get_dossiers(store, filters, **kwargs):
        asked.append(filters.status)
        return {"total": 1, "items": [_DOSSIER]}

    monkeypatch.setattr("lawgraph.api.routes.dossiers.get_dossiers", get_dossiers)
    body = client.get("/api/dossiers?status=open").json()
    assert client.get("/api/dossiers").status_code == 200
    assert asked == ["open", None]  # all by default
    assert body["total"] == 1
    assert body["items"][0]["number"] == "36000"
    assert body["items"][0]["title"] == "Testwet"
    assert body["items"][0]["kind"] == "Wetgeving"
    assert body["items"][0]["current_phase"] == "Voorstel van wet"
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
    # what the detail links to is empty: the hub is shaped in test_dossier_hub_api.py
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.enrich_dossier_docs",
        lambda store, dossiers: dossiers,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_relations",
        lambda store, dossier_id: [],
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_hub", lambda store, dossier_id: {}
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_laws_named", lambda store, names: []
    )
    body = client.get("/api/dossiers/36000").json()
    assert body["number"] == "36000"
    assert body["document_count"] == 4
    assert body["decision_count"] == 2
    assert body["commitment_count"] == 0


def test_party_colors_are_served_under_parties() -> None:
    body = client.get("/api/parties/colors").json()
    assert body["colors"]["VVD"].startswith("#")


_DOCUMENT_ROW = {
    "id": "documents/mvt",
    "key": "mvt",
    "kind": "Memorie van toelichting",
    "title": "MvT",
    "sequence": 3,
    "session_year": "2024-2025",
    "date": "2025-01-10",
    "document_number": "2025D00003",
    "display_name": "MvT",
    "source": "tk",
    "labels": ["TK"],
}


def test_the_documents_of_a_dossier_say_their_chamber_and_kind(monkeypatch) -> None:
    ek = {**_DOCUMENT_ROW, "key": "ek_1", "source": "eerstekamer", "labels": ["EK"]}
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_number",
        lambda store, number: _DOSSIER,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_documents",
        lambda store, dossier_id, **kwargs: {
            "total": 2,
            "items": [_DOCUMENT_ROW, {**ek, "kind": "Verslag"}],
        },
    )
    listed = client.get("/api/dossiers/36000/documents").json()["items"]
    assert [(d["chamber"], d["source"], d["is_explanatory"]) for d in listed] == [
        ("TK", "tk", True),
        ("EK", "eerstekamer", False),
    ]


_MVT_PAGE = (
    "https://www.tweedekamer.nl/kamerstukken/detail?id=2025D00003&did=2025D00003"
)

_TIMELINE_ROWS = [
    {
        "date": "2025-01-10",
        "kind": "Memorie van toelichting",
        "title": "MvT",
        "body": {
            "kind": "Memorie van toelichting",
            "title": "MvT",
            "sequence": 3,
            "dossier_number": "36000",
            "session_year": "2024-2025",
            "document_number": "2025D00003",
            "source": "tk",
        },
        "labels": ["TK"],
        "node_id": "documents/mvt",
        "node_type": "document",
        "committee": None,
    },
    {
        "date": "2025-03-06",
        "kind": "Commissiedebat",
        "title": "Debat",
        "body": {
            "kind": "Commissiedebat",
            "agenda_title": "2025-03-06 - Debat",
            "number": "2025A00001",
        },
        "labels": ["TK"],
        "node_id": "activities/a1",
        "node_type": "activity",
        "committee": {"key": "ienw", "slug": "ienw", "name": "Infrastructuur"},
    },
    {
        "date": "2025-03-08",
        "kind": "Stemming",
        "title": "Stemming",
        "body": {
            "subject": "Motie",
            "passed": True,
            "tally": {"Voor": 80},
            "voters": {"Voor": 5},
            "decision_id": "b1",
            "document": {
                "id": "documents/motie",
                "key": "motie",
                "kind": "Motie",
                "chamber": "TK",
                "source": "tk",
                "is_explanatory": False,
                "dictum_excerpt": "De Kamer verzoekt",
                "signatories": [
                    {"name": "Lid A", "role": "indiener", "source_role": "Eerste"}
                ],
            },
        },
        "labels": ["TK"],
        "node_id": "decisions/d1",
        "node_type": "decision",
        "committee": None,
    },
    {
        "date": "2025-03-11",
        "kind": "Toezegging",
        "title": "Toezegging",
        "body": {"text": "De minister zegt toe.", "status": "open"},
        "labels": ["TK"],
        "node_id": "commitments/t1",
        "node_type": "commitment",
        "committee": None,
    },
]


def test_the_timeline_entries_are_typed_by_their_node(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_number",
        lambda store, number: _DOSSIER,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_timeline",
        lambda store, dossier_id, **kwargs: _TIMELINE_ROWS,
    )
    body = client.get("/api/dossiers/36000/timeline").json()
    document, activity, decision, commitment = body["entries"]

    assert document["body"] == {
        "chamber": "TK",
        "source": "tk",
        "is_explanatory": True,
        "kind": "Memorie van toelichting",
        "title": "MvT",
        "sequence": 3,
        "dossier_number": "36000",
        "session_year": "2024-2025",
        "tk_url": _MVT_PAGE,
        "url": None,
    }
    # The pages on tweedekamer.nl follow from the numbers, never from a stored link.
    assert document["tk_url"] == _MVT_PAGE
    assert activity["tk_url"] == (
        "https://www.tweedekamer.nl/debat_en_vergadering/commissievergaderingen/"
        "details?id=2025A00001"
    )
    assert decision["tk_url"] is None and commitment["tk_url"] is None
    assert "committee" not in document
    assert activity["committee"] == {
        "key": "ienw",
        "slug": "ienw",
        "name": "Infrastructuur",
    }
    assert activity["body"]["agenda_title"] == "2025-03-06 - Debat"
    assert decision["body"]["tally"] == {"Voor": 80}
    assert decision["body"]["external_id"] == "b1"
    assert decision["body"]["document"]["signatories"][0]["role"] == "indiener"
    assert decision["body"]["document"]["chamber"] == "TK"
    assert commitment["body"]["text"] == "De minister zegt toe."
    assert commitment["body"]["status"] == "open"


def test_a_plenary_activity_has_no_committee() -> None:
    from lawgraph.api.schemas.dossiers import timeline_entry

    plenary = {**_TIMELINE_ROWS[1], "committee": None}
    assert timeline_entry(plenary).model_dump()["committee"] is None  # type: ignore[union-attr]


# ── committees, members, factions ────────────────────────────────────────────


def test_committees_are_listed_with_english_field_names(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_committees",
        lambda store, **kwargs: [_COMMITTEE],
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
        lambda store, filters, **kwargs: {"total": 1, "items": [_DECISION]},
    )
    body = client.get("/api/decisions").json()
    assert body["total"] == 1
    assert body["items"][0]["tally"] == {"Voor": 76, "Tegen": 74}
    assert body["items"][0]["vote_kind"] == "faction"
    assert body["items"][0]["kind"] == "Motie"
    assert body["facets"] == {"kind": [], "passed": [], "days": []}


def _asking(monkeypatch) -> list[DecisionFilters]:
    asked: list[DecisionFilters] = []

    def fake(store, filters, **kwargs):
        asked.append(filters)
        return {"total": 1, "items": [_DECISION]}

    monkeypatch.setattr("lawgraph.api.routes.decisions.get_decisions", fake)
    return asked


def test_decisions_are_filtered_by_dossier(monkeypatch) -> None:
    asked = _asking(monkeypatch)
    assert client.get("/api/decisions?dossier=36000").json()["total"] == 1
    assert asked[0].dossier == "36000"
    assert client.get("/api/decisions?dossier=x").status_code == 422


def test_decisions_are_filtered_by_kind_date_subject_and_how_a_party_voted(
    monkeypatch,
) -> None:
    asked = _asking(monkeypatch)
    response = client.get(
        "/api/decisions",
        params={
            "kind": "Motie, Amendement",
            "from": "2024-01-01",
            "to": "2024-12-31",
            "q": "  Wachtlijsten ",
            "party": "VVD",
            "vote": "tegen",
        },
    )
    assert response.status_code == 200
    assert asked[0] == DecisionFilters(
        kinds=("Motie", "Amendement"),
        party="VVD",
        choice="Tegen",
        date_from="2024-01-01",
        date_to="2024-12-31",
        q="Wachtlijsten",
    )


@pytest.mark.parametrize(
    "params",
    [
        {"vote": "voor"},  # how, without whom
        {"party": "VVD", "vote": "onthouden"},
        {"from": "2024-13-01"},
    ],
)
def test_a_decision_filter_it_cannot_read_is_a_422(monkeypatch, params) -> None:
    _asking(monkeypatch)
    assert client.get("/api/decisions", params=params).status_code == 422


def test_the_decision_facets_are_passed_on(monkeypatch) -> None:
    facets = {
        "kind": [{"value": "Motie", "count": 3}, {"value": None, "count": 1}],
        "passed": [{"value": True, "count": 3}, {"value": None, "count": 1}],
        "days": [{"date": "2024-10-16", "count": 4, "passed": 3}],
    }
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decisions",
        lambda store, filters, **kwargs: {
            "total": 4,
            "items": [_DECISION],
            "facets": facets,
        },
    )
    assert client.get("/api/decisions").json()["facets"] == facets


def test_a_decisions_document_carries_its_links(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decision_detail",
        lambda store, key: {"_id": "decisions/d", "_key": "d", "props": {}},
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_decision_document",
        lambda store, decision: {
            "_id": "documents/m",
            "_key": "m",
            "labels": ["TK"],
            "props": {"kind": "Motie", "source": "tk"},
        },
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.decisions.get_document_links",
        lambda store, document_id: {"dossier_numbers": ["36000"], "explains": []},
    )
    body = client.get("/api/decisions/d/document").json()
    assert body["chamber"] == "TK" and body["dossier_numbers"] == ["36000"]


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
    # the order follows the plan of the Tweede Kamer, which the answer names
    assert body["seating_plan"]["dated"] == "2026-06-01"
    assert "wie-zit-waar" in body["seating_plan"]["page"]


def test_the_seats_on_a_day_are_those_the_members_held(monkeypatch) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.parliament.get_factions",
        lambda store, **kwargs: [_FACTION],
    )
    asked: list[str] = []

    def seats_on(store, day):
        asked.append(day)
        return {"vvd": 33}

    monkeypatch.setattr("lawgraph.api.routes.parliament.get_seats_on", seats_on)
    body = client.get("/api/parliament/seats?date=2010-10-10").json()
    assert asked == ["2010-10-10"]
    assert body["as_of"] == "2010-10-10"
    assert [(f["key"], f["seats"]) for f in body["factions"]] == [("vvd", 33)]
    assert body["assigned_seats"] == 33
    assert client.get("/api/parliament/seats?date=gisteren").status_code == 422
