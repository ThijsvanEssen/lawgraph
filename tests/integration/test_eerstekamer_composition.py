"""The composition of the Eerste Kamer from its pages, on a real database, over two snapshots.

The first (2026-09-30) holds the D66 faction and the committee for Financiën; B.O. Dittrich
was a member of the Tweede Kamer, and matches that member by his date of birth and surname.
In the second (2026-10-07) R.S. Croll no longer sits in the D66 faction.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    RAW_KIND_EK_COMPOSITION,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CROLL = "/persoon/mr_r_s_croll_d66"


def _pages() -> dict[str, str]:
    return {
        "/fracties": (FIXTURES / "ek_factions.html").read_text(),
        "/fractie/democraten_1966": (FIXTURES / "ek_faction_d66.html").read_text(),
        "/commissies": (FIXTURES / "ek_committees.html").read_text(),
        "/commissies/fin": (FIXTURES / "ek_committee_fin.html").read_text(),
    }


def _store_snapshot(store: ArangoStore, pages: dict[str, str], day: str) -> None:
    with RawSourceWriter(store) as writer:
        for path, html in pages.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EK_COMPOSITION,
                    external_id=path,
                    payload_text=html,
                    meta={"url": f"https://www.eerstekamer.nl{path}", "read_on": day},
                )
            )


def _without_croll(html: str) -> str:
    """The page without the list item of Croll."""
    return re.sub(
        rf'<li class="persoon[^"]*">\s*<a href="{CROLL}">.*?</li>', "", html, flags=re.S
    )


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[ArangoStore]:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection=COLLECTION_MEMBERS,
                type=NodeType.MEMBER,
                key="dittrich",
                labels=["TK"],
                props={
                    "name": "Boris Dittrich",
                    "family_name": "Dittrich",
                    "birth_date": "1955-07-21",
                },
            )
        )
    _store_snapshot(store, _pages(), "2026-09-30")
    cli("normalize", "eerstekamer-composition")
    yield store


def _members(store: ArangoStore) -> dict[str, dict[str, Any]]:
    return {
        row["ek"]["path"]: row
        for row in store.query(
            "SELECT key, props -> 'ek' AS ek FROM members"
            " WHERE coalesce(json_typeof(props -> 'ek'), 'null') <> 'null'"
        )
    }


def test_a_snapshot_makes_the_factions_committees_and_members(
    store: ArangoStore, cli: Any
) -> None:
    faction = store.get_document("factions", "ek_democraten_1966")["props"]
    assert (faction["chamber"], faction["abbreviation"], faction["seats"]) == (
        "EK",
        "D66",
        7,
    )
    assert (
        faction["observed_from"] == "2026-09-30" and faction["observed_until"] is None
    )
    assert faction["board"][0] == {
        "function": "fractievoorzitter",
        "name": "Paul van Meenen",
        "member": "ek_drs_p_h_van_meenen_d66",
        "since": "2023-06-13",
    }
    members = _members(store)
    assert len(members) == 7
    # a member of the Tweede Kamer is the same person: one member node
    assert members["/persoon/mr_b_o_dittrich_d66"]["key"] == "dittrich"
    assert members[CROLL]["key"] == "ek_mr_r_s_croll_d66"
    assert members[CROLL]["ek"]["seniority_days"] == 1205
    committee = store.get_document("committees", "ek_fin")["props"]
    assert (committee["slug"], committee["abbreviation"]) == ("ek-fin", "FIN")

    # a week later Croll is no longer shown: observed until that day, the others unchanged
    pages = _pages()
    pages["/fractie/democraten_1966"] = _without_croll(
        pages["/fractie/democraten_1966"]
    )
    _store_snapshot(store, pages, "2026-10-07")
    cli("normalize", "eerstekamer-composition")
    members = _members(store)
    assert members[CROLL]["ek"]["observed_until"] == "2026-10-07"
    # the first snapshot stays the start of what is known
    faction = store.get_document("factions", "ek_democraten_1966")["props"]
    assert (faction["retrieved_on"], faction["data_since"]) == (
        "2026-10-07",
        "2026-09-30",
    )
    dittrich = members["/persoon/mr_b_o_dittrich_d66"]["ek"]
    assert (dittrich["observed_from"], dittrich["observed_until"]) == (
        "2026-09-30",
        None,
    )
    edges = list(
        store.query(
            "SELECT json_build_array(from_id, doc -> 'meta' -> 'observed_from',"
            " doc -> 'meta' -> 'observed_until') FROM edges"
            " WHERE relation = 'MEMBER_OF' AND to_id = 'factions/ek_democraten_1966'"
        )
    )
    assert ["members/ek_mr_r_s_croll_d66", "2026-09-30", "2026-10-07"] in edges
    assert ["members/dittrich", "2026-09-30", None] in edges


def test_the_api_shows_the_eerste_kamer_beside_the_tweede(store: ArangoStore) -> None:
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        factions = client.get("/api/factions", params={"chamber": "EK"}).json()
        assert [
            (f["abbreviation"], f["seats"], f["member_count"]) for f in factions
        ] == [("D66", 7, 7)]
        assert factions[0]["source"]["attribution"].startswith("Eerste Kamer")
        assert factions[0]["source"]["composition_date"] == "2026-09-30"
        assert factions[0]["source"]["data_since"] == "2026-09-30"
        assert factions[0]["board"][0]["function"] == "fractievoorzitter"
        # the Tweede Kamer's lists do not hold them
        assert client.get("/api/factions").json() == []
        assert client.get("/api/committees").json() == []

        committees = client.get("/api/committees", params={"chamber": "EK"}).json()
        assert [c["slug"] for c in committees] == ["ek-fin"]
        fin = client.get("/api/committees/ek-fin").json()
        # of the members this snapshot knows (the D66 faction), two sit on Financiën
        assert sorted((m["key"], m["role"]) for m in fin["members"]) == [
            ("ek_drs_a_griffioen_d66", None),
            ("ek_ir_ing_c_p_m_moonen_d66", None),
        ]
        assert fin["members"][0]["observed_from"] == "2026-09-30"

        members = client.get("/api/members", params={"chamber": "EK"}).json()
        assert len(members) == 7
        dittrich = next(m for m in members if m["key"] == "dittrich")
        assert dittrich["ek"]["abbreviation"] == "D66"
        assert dittrich["ek"]["observed_from"] == "2026-09-30"
        # in the list of the Eerste Kamer, its party and whether it sits there now
        assert {(m["party"], m["active"]) for m in members} == {("D66", True)}

        seats = client.get("/api/parliament/seats", params={"chamber": "EK"}).json()
        assert (seats["chamber"], seats["total_seats"], seats["assigned_seats"]) == (
            "EK",
            75,
            7,
        )
        assert seats["seating_plan"] is None
        assert seats["source"]["data_since"] == "2026-09-30"
        assert (
            client.get(
                "/api/parliament/seats", params={"chamber": "EK", "date": "2026-01-01"}
            ).status_code
            == 422
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
