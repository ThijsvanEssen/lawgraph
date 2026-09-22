"""The dossier hub, the committee pages and the authorship lists: how the rows are shaped."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import committees as committee_routes
from lawgraph.api.schemas.committees import ActorDossierDTO, CommitteeDetailDTO

client = TestClient(app)

_DOSSIER = {
    "_id": "dossiers/36000",
    "_key": "36000",
    "props": {
        "number": "36000",
        "title": "Testwet",
        "title_source": "dossier",
        "current_stage": "wetsvoorstel",
        "stages_present": ["wetsvoorstel"],
        "track_kind": "wetsvoorstel",
        "closed": False,
        "opened_on": "2024-01-01",
    },
}

_HUB = {
    "instruments": [
        {
            "id": "instruments/bwbr0000001",
            "key": "bwbr0000001",
            "bwb_id": "BWBR0000001",
            "celex": None,
            "display_name": "Wet A",
            "jurisdiction": "nl",
            "relation": "legislated_in",
            "status": "canoniek",
        },
        {
            "id": "instruments/32016l0680",
            "key": "32016l0680",
            "bwb_id": None,
            "celex": "32016L0680",
            "display_name": "Richtlijn X",
            "jurisdiction": "eu",
            "relation": "amends",
            "status": "voorgesteld",
        },
    ],
    "committees": [
        {
            "id": "committees/c_a",
            "key": "c_a",
            "slug": "a",
            "name": "Commissie A",
            "abbreviation": "CA",
        }
    ],
    "documents_by_kind": {"Motie": 3, "Brief": 2},
    "senate": {"document_count": 2, "first_date": "2024-04-01"},
}


class _MockStore:
    def get_node(self, collection: str, key: str) -> Any:
        return None

    def query(self, aql: str, bind_vars: dict | None = None) -> Any:
        return iter([])


@pytest.fixture(autouse=True)
def _mock_store() -> Any:
    app.dependency_overrides[get_store] = lambda: _MockStore()
    committee_routes._faction_dossiers_cache.clear()
    yield
    app.dependency_overrides.pop(get_store, None)


def _dossier_routes(monkeypatch: pytest.MonkeyPatch, hub: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_by_number",
        lambda store, number: _DOSSIER,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.count_dossier_members",
        lambda store, dossier_id: {"documents": 5},
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.dossiers.get_dossier_hub",
        lambda store, dossier_id: hub,
    )


def test_the_dossier_detail_carries_its_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    _dossier_routes(monkeypatch, _HUB)

    body = client.get("/api/dossiers/36000").json()

    assert body["document_count"] == 5  # what it had before
    assert body["instruments"][0] == _HUB["instruments"][0]
    assert body["instruments"][1]["celex"] == "32016L0680"
    assert body["instruments"][1]["bwb_id"] is None
    assert body["committees"] == [{**_HUB["committees"][0], "role": "lead"}]
    assert body["documents_by_kind"] == {"Motie": 3, "Brief": 2}
    assert body["senate"] == {"document_count": 2, "first_date": "2024-04-01"}


def test_a_dossier_without_links_has_an_empty_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dossier_routes(monkeypatch, {})

    body = client.get("/api/dossiers/36000").json()

    assert body["instruments"] == [] and body["committees"] == []
    assert body["documents_by_kind"] == {}
    assert body["senate"] == {"document_count": 0, "first_date": None}


def test_an_instrument_relation_the_catalogue_lacks_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = {"instruments": [{**_HUB["instruments"][0], "relation": "explains"}]}
    _dossier_routes(monkeypatch, hub)

    with pytest.raises(ValueError):
        client.get("/api/dossiers/36000")


def test_the_committee_detail_pages_its_dossiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def detail(store: Any, slug: str, **kwargs: Any) -> dict[str, Any]:
        asked.update(kwargs)
        return {
            "_id": "committees/c_a",
            "_key": "c_a",
            "props": {"name": "Commissie A", "slug": "a"},
            "members": [],
            "dossiers": [_DOSSIER],
            "dossier_total": 240,
            "open_dossier_count": 17,
        }

    monkeypatch.setattr("lawgraph.api.routes.committees.get_committee_detail", detail)

    body = client.get("/api/committees/a?status=closed&limit=1&offset=5").json()

    assert asked["status"] == "closed" and asked["limit"] == 1 and asked["offset"] == 5
    assert body["dossier_total"] == 240
    assert body["active_dossier_count"] == 17  # open ones of all, not of the page
    assert [d["number"] for d in body["dossiers"]] == ["36000"]


@pytest.mark.parametrize(
    "query", ["status=archived", "limit=0", "limit=501", "offset=-1"]
)
def test_the_committee_dossier_paging_has_bounds(query: str) -> None:
    assert client.get(f"/api/committees/a?{query}").status_code == 422


def test_the_committee_detail_dto_counts_from_the_query_not_from_the_page() -> None:
    dto = CommitteeDetailDTO.from_detail_document(
        {
            "_id": "committees/c_a",
            "_key": "c_a",
            "props": {},
            "dossiers": [{**_DOSSIER, "props": {**_DOSSIER["props"], "closed": True}}],
            "dossier_total": 9,
            "open_dossier_count": 4,
        }
    )
    assert dto.dossier_total == 9 and dto.active_dossier_count == 4


def test_committee_activities_are_paged_with_a_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_committee_activities",
        lambda store, slug, **kwargs: {
            "total": 41,
            "items": [
                {
                    "id": "activities/a1",
                    "key": "a1",
                    "date": "2024-06-01",
                    "kind": "Commissiedebat",
                    "agenda_title": "Debat",
                    "dossier_numbers": ["36000"],
                },
                {"id": "activities/a2", "key": "a2"},
            ],
        },
    )

    body = client.get("/api/committees/a/activities?limit=2").json()

    assert body["total"] == 41
    assert body["items"][0]["dossier_numbers"] == ["36000"]
    assert body["items"][1] == {
        "id": "activities/a2",
        "key": "a2",
        "date": None,
        "kind": None,
        "agenda_title": None,
        "dossier_numbers": [],
    }


def test_the_activities_of_an_unknown_committee_are_a_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.committees.get_committee_activities",
        lambda store, slug, **kwargs: None,
    )
    assert client.get("/api/committees/nope/activities").status_code == 404


def test_an_actor_dossier_is_a_dossier_summary_with_roles_and_a_count() -> None:
    dto = ActorDossierDTO.from_row(
        {
            "dossier": _DOSSIER,
            "roles": ["Eerste ondertekenaar", "Mede ondertekenaar"],
            "document_count": 3,
        }
    )
    assert dto.number == "36000" and dto.title == "Testwet"
    assert dto.roles == ["Eerste ondertekenaar", "Mede ondertekenaar"]
    assert dto.document_count == 3
    assert ActorDossierDTO.from_row({"dossier": _DOSSIER}).roles == []


class _FoundStore(_MockStore):
    def get_node(self, collection: str, key: str) -> Any:
        from lawgraph.core.models import Node, NodeType

        return Node(
            collection=collection,
            type=NodeType.MEMBER if collection == "members" else NodeType.FACTION,
            key=key,
            _skip_validation=True,
        )


@pytest.mark.parametrize(
    ("path", "actor_id"),
    [("members/p1", "members/p1"), ("factions/vvd", "factions/vvd")],
)
def test_members_and_factions_list_their_dossiers(
    monkeypatch: pytest.MonkeyPatch, path: str, actor_id: str
) -> None:
    app.dependency_overrides[get_store] = lambda: _FoundStore()
    seen: dict[str, Any] = {}

    def dossiers(store: Any, actor: str, **kwargs: Any) -> dict[str, Any]:
        seen.update(actor=actor, **kwargs)
        return {
            "total": 12,
            "items": [
                {
                    "dossier": _DOSSIER,
                    "roles": ["Eerste ondertekenaar"],
                    "document_count": 2,
                }
            ],
        }

    monkeypatch.setattr("lawgraph.api.routes.committees.get_actor_dossiers", dossiers)

    body = client.get(f"/api/{path}/dossiers?limit=5&offset=10").json()

    assert seen == {"actor": actor_id, "limit": 5, "offset": 10}
    assert body["actor_id"] == actor_id and body["total"] == 12
    assert body["items"][0]["number"] == "36000"
    assert body["items"][0]["roles"] == ["Eerste ondertekenaar"]
    assert body["items"][0]["document_count"] == 2


@pytest.mark.parametrize("path", ["members/nobody", "factions/nobody"])
def test_the_dossiers_of_an_unknown_actor_are_a_404(path: str) -> None:
    assert client.get(f"/api/{path}/dossiers").status_code == 404
