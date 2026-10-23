"""The dossier hub, the committee pages and the authorship lists: how the rows are shaped."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api import actors
from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.actors import ActorDossierDTO
from tests.api.stubs import MockStore, stub_route
from tests.asserts import assert_status

client = TestClient(app)

_DOSSIER: dict[str, Any] = {
    "id": "dossiers/36000",
    "key": "36000",
    "props": {
        "number": "36000",
        "label": "36000",
        "title": "Testwet",
        "title_source": "dossier",
        "kind": "Wetgeving",
        "kind_basis": "case",
        "phases": [],
        "current_phase": None,
        "closed": False,
        "opened_on": "2024-01-01",
    },
}

_HUB: dict[str, Any] = {
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


def _dossier_routes(
    monkeypatch: pytest.MonkeyPatch,
    hub: dict[str, Any],
    asked: list[bool] | None = None,
) -> None:
    def read_hub(store: Any, dossier_id: str, *, importance: bool = False) -> Any:
        if asked is not None:
            asked.append(importance)
        return hub

    stub_route(
        monkeypatch,
        "dossiers",
        get_dossier_by_number=_DOSSIER,
        count_dossier_members={"documents": 5},
        get_dossier_hub=read_hub,
        enrich_dossier_docs=lambda store, dossiers: dossiers,
        get_dossier_relations=[],
        get_laws_named=[],
        get_dossier_implements=[],
        get_instrument_names={},
        get_next_activity=None,
        get_member_brief=lambda store, key: {
            "name": "H.M. de Jonge",
            "slug": "h-m-de-jonge",
        },
    )


def test_the_dossier_detail_carries_its_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    _dossier_routes(monkeypatch, _HUB)

    body = client.get("/api/dossiers/36000").json()

    assert body["document_count"] == 5  # what it had before
    assert body["instruments"][0] == {
        **_HUB["instruments"][0],
        "links": [{"relation": "legislated_in", "status": "canoniek"}],
    }
    assert body["instruments"][1]["celex"] == "32016L0680"
    assert body["instruments"][1]["bwb_id"] is None
    assert body["committees"] == [
        {**_HUB["committees"][0], "role": "lead", "path": "/commissies/a"}
    ]
    assert body["documents_by_kind"] == {"Motie": 3, "Brief": 2}
    # no page of its bill: nothing of it
    assert body["senate"] == {
        "document_count": 2,
        "first_date": "2024-04-01",
        "submitted_on": None,
        "status": None,
        "progress": [],
        "source": None,
    }


def test_the_dossier_detail_ranks_its_hub_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[bool] = []
    _dossier_routes(monkeypatch, _HUB, asked)

    client.get("/api/dossiers/36000")
    client.get("/api/dossiers/36000?sort=importance")

    assert asked == [False, True]
    assert_status(client.get("/api/dossiers/36000?sort=best"), 422)


def test_a_dossier_without_links_has_an_empty_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dossier_routes(monkeypatch, {})

    body = client.get("/api/dossiers/36000").json()

    assert body["instruments"] == [] and body["committees"] == []
    assert body["enacted"] == []
    assert body["documents_by_kind"] == {}
    assert body["senate"] == {
        "document_count": 0,
        "first_date": None,
        "submitted_on": None,
        "status": None,
        "progress": [],
        "source": None,
    }


def test_the_dossier_detail_names_the_publications_its_law_was_enacted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enacted: list[dict[str, Any]] = [
        {
            "key": "stb_2024_193",
            "cite": "Stb. 2024, 193",
            "signed_on": "2024-06-26",
            "published_on": "2024-06-26",
            "commencement": {
                "key": "stb_2024_197",
                "cite": "Stb. 2024, 197",
                "published_on": "2024-06-28",
            },
            "first_effective_date": "2024-07-01",
            "instrument": {"key": "bwbr0049889", "title": "Wet betaalbare huur"},
        },
        {
            "key": "stb_2026_56",
            "cite": "Stb. 2026, 56",
            "signed_on": None,
            "published_on": "2026-03-01",
            "commencement": None,
            "first_effective_date": None,
            "instrument": {
                "key": "wet_stb_2026_56",
                "title": "Wetboek van Strafvordering",
            },
        },
        {
            "key": "stb_2025_10",
            "cite": "Stb. 2025, 10",
            "signed_on": None,
            "published_on": "2025-01-15",
            "commencement": None,
            "first_effective_date": "2025-02-01",
            "instrument": None,
        },
    ]
    _dossier_routes(monkeypatch, {**_HUB, "enacted": enacted})

    body = client.get("/api/dossiers/36000").json()

    assert body["enacted"] == [
        {
            **enacted[0],
            "commencement": {**enacted[0]["commencement"], "path": "/stb/2024/197"},
            "path": "/stb/2024/193",
            "instrument": {**enacted[0]["instrument"], "path": "/wetten/BWBR0049889"},
        },
        {
            **enacted[1],
            "path": "/stb/2026/56",
            "instrument": {**enacted[1]["instrument"], "path": "/wetten/STB-2026-56"},
        },
        {**enacted[2], "path": "/stb/2025/10"},
    ]


def test_the_dossier_detail_names_the_government_and_the_end_of_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    props = {
        **_DOSSIER["props"],
        "ministry": "bzk",
        "initiative": False,
        "cabinet": "rutte_iv",
        "first_signed": {
            "date": "2024-02-05",
            "member": "h_m_de_jonge",
            "capacity": "bewindspersoon",
            "function": "minister voor Volkshuisvesting en Ruimtelijke Ordening",
            "paper": "documents/kst-36000-2",
        },
        "ek_bill": {
            "url": "https://www.eerstekamer.nl/wetsvoorstel/36000_testwet",
            "progress": [
                {
                    "phase": "Afkondiging",
                    "house": "Staatsblad(en)",
                    "state": "vol",
                    "papers": [
                        {
                            "kind": "publicatie inwerkingtreding",
                            "date": "2024-06-28",
                            "url": "u1",
                        },
                        {"kind": "publicatie wet", "date": "2024-06-28", "url": "u2"},
                        {"kind": "publicatie wet", "date": "2023-01-01", "url": "u3"},
                        {"kind": "verslag", "date": "2024-06-28", "url": "u4"},
                    ],
                }
            ],
        },
    }
    enacted = [
        {
            "key": "stb_2024_193",
            "cite": "Stb. 2024, 193",
            "signed_on": "2024-06-26",
            "published_on": "2024-06-28",
            "commencement": {
                "key": "stb_2024_197",
                "cite": "Stb. 2024, 197",
                "published_on": "2024-06-28",
            },
            "first_effective_date": "2024-07-01",
            "instrument": None,
        },
        {
            "key": "stb_2099_1",
            "cite": "Stb. 2099, 1",
            "signed_on": None,
            "published_on": "2099-01-01",
            "commencement": None,
            "first_effective_date": "2099-02-01",
            "instrument": None,
        },
    ]
    _dossier_routes(monkeypatch, {**_HUB, "enacted": enacted})
    monkeypatch.setitem(_DOSSIER, "props", props)

    body = client.get("/api/dossiers/36000").json()

    assert body["proposed_by"] == {
        "member_key": "h_m_de_jonge",
        "name": "H.M. de Jonge",
        "function": "minister voor Volkshuisvesting en Ruimtelijke Ordening",
        "capacity": "bewindspersoon",
        "date": "2024-02-05",
        "ministry": "bzk",
        "path": "/leden/h-m-de-jonge",
    }
    assert body["in_force_since"] == "2024-07-01"  # not the law of 2099
    papers = body["senate"]["progress"][0]["papers"]
    assert [p["path"] for p in papers] == ["/stb/2024/197", "/stb/2024/193", None, None]


def test_a_dossier_nobody_signed_has_no_proposer_and_is_not_in_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dossier_routes(monkeypatch, _HUB)

    body = client.get("/api/dossiers/36000").json()

    assert body["proposed_by"] is None and body["in_force_since"] is None


def test_an_instrument_relation_the_catalogue_lacks_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = {"instruments": [{**_HUB["instruments"][0], "relation": "explains"}]}
    _dossier_routes(monkeypatch, hub)

    response = client.get("/api/dossiers/36000")
    assert response.status_code == 500, response.text


def test_the_committee_detail_pages_its_dossiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def detail(store: Any, slug: str, **kwargs: Any) -> dict[str, Any]:
        asked.update(kwargs)
        return {
            "id": "committees/c_a",
            "key": "c_a",
            "props": {"name": "Commissie A", "slug": "a", "active_dossier_count": 17},
            "members": [],
            "dossiers": [_DOSSIER],
            "dossier_total": 240,
        }

    stub_route(monkeypatch, "committees", get_committee_detail=detail)

    body = client.get("/api/committees/a?status=closed&limit=1&offset=5").json()

    assert asked["status"] == "closed" and asked["limit"] == 1 and asked["offset"] == 5
    assert body["dossier_total"] == 240
    assert body["active_dossier_count"] == 17  # the stored count, not the page
    assert [d["number"] for d in body["dossiers"]] == ["36000"]


@pytest.mark.parametrize(
    "query", ["status=archived", "limit=0", "limit=501", "offset=-1"]
)
def test_the_committee_dossier_paging_has_bounds(query: str) -> None:
    assert_status(client.get(f"/api/committees/a?{query}"), 422)


def test_committee_activities_are_paged_with_a_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_route(
        monkeypatch,
        "committees",
        get_committee_activities={
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
    # the names of its dossiers next to the numbers (``load_dossier_names``)
    assert body["items"][0]["dossiers"] == [
        {
            "number": "36000",
            "short_title": "Wet beter voorbeeld",
            "title": "Wijziging van de Wet X (Wet beter voorbeeld)",
        }
    ]
    assert body["items"][1] == {
        "id": "activities/a2",
        "key": "a2",
        "date": None,
        "kind": None,
        "agenda_title": None,
        "status": None,
        "dossier_numbers": [],
        "dossiers": [],
    }


def test_the_activities_of_an_unknown_committee_are_a_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_route(monkeypatch, "committees", get_committee_activities=None)
    assert_status(client.get("/api/committees/nope/activities"), 404)


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


class _FoundStore(MockStore):
    def get_document(self, collection: str, key: str) -> Any:
        return {"id": f"{collection}/{key}", "key": key, "type": collection[:-1],
                "labels": [], "props": {}}  # fmt: skip


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

    monkeypatch.setattr(actors, "get_actor_dossiers", dossiers)

    body = client.get(f"/api/{path}/dossiers?limit=5&offset=10").json()

    assert seen == {"actor": actor_id, "limit": 5, "offset": 10, "sort": "opened"}
    assert body["actor_id"] == actor_id and body["total"] == 12
    assert body["items"][0]["number"] == "36000"
    assert body["items"][0]["roles"] == ["Eerste ondertekenaar"]
    assert body["items"][0]["document_count"] == 2


@pytest.mark.parametrize("path", ["members/nobody", "factions/nobody"])
def test_the_dossiers_of_an_unknown_actor_are_a_404(path: str) -> None:
    assert_status(client.get(f"/api/{path}/dossiers"), 404)
