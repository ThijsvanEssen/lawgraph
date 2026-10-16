"""The composition of the Eerste Kamer from its pages, on a real database, over two snapshots.

The first (2026-09-30) holds the D66 faction and the committee for Financiën; B.O. Dittrich
was a member of the Tweede Kamer, and matches that member by his date of birth and surname.
In the second (2026-10-07) R.S. Croll no longer sits in the D66 faction. The pages are stored
as ``retrieve eerstekamer-composition`` stores them: a version per day a page changed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    RAW_KIND_EERSTEKAMER_COMPOSITION,
)
from lawgraph.core.models import Node
from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.queries import ek_seats
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.pipelines.retrieve.eerstekamer_composition import (
    EerstekamerCompositionRetrievePipeline,
)
from tests.optional import present

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CROLL = "/persoon/mr_r_s_croll_d66"


def _pages() -> dict[str, str]:
    return {
        "/fracties": (FIXTURES / "ek_factions.html").read_text(),
        "/fractie/democraten_1966": (FIXTURES / "ek_faction_d66.html").read_text(),
        "/commissies": (FIXTURES / "ek_committees.html").read_text(),
        "/commissies/fin": (FIXTURES / "ek_committee_fin.html").read_text(),
        "/wie_zit_waar": (FIXTURES / "ek_wie_zit_waar.html").read_text(),
    }


def _store_snapshot(store: GraphStore, pages: dict[str, str], day: str) -> None:
    """The pages as ``retrieve eerstekamer-composition`` stores them when read on *day*."""
    pipeline = EerstekamerCompositionRetrievePipeline(
        store, cast(EerstekamerSiteClient, object())
    )
    read = [
        (path, f"https://www.eerstekamer.nl{path}", html)
        for path, html in pages.items()
    ]
    assert not pipeline._store_all(pipeline.records(read, day)).errors


def _versions(store: GraphStore) -> dict[str, tuple[str, str]]:
    """``external_id: (read_on, last_read_on)`` of every stored page."""
    return {
        row["id"]: (row["read_on"], row["last_read_on"])
        for row in store.query(
            "SELECT external_id AS id, doc -> 'meta' ->> 'read_on' AS read_on,"
            " doc -> 'meta' ->> 'last_read_on' AS last_read_on FROM raw_sources"
            " WHERE kind = %(kind)s",
            {"kind": RAW_KIND_EERSTEKAMER_COMPOSITION},
        )
    }


def _dittrich(store: GraphStore) -> None:
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection=COLLECTION_MEMBERS,
                key="dittrich",
                labels=["TK"],
                props={
                    "name": "Boris Dittrich",
                    "family_name": "Dittrich",
                    "birth_date": "1955-07-21",
                },
            )
        )


def _empty_graph(store: GraphStore) -> None:
    """The graph without the composition, as a rebuild starts (the member of the Tweede
    Kamer it is matched to is there again)."""
    for table in ("edges", "factions", "committees", "members"):
        store.execute(f"DELETE FROM {table}")
    _dittrich(store)


def _without_croll(html: str) -> str:
    """The page without the list item of Croll."""
    return re.sub(
        rf'<li class="persoon[^"]*">\s*<a href="{CROLL}">.*?</li>', "", html, flags=re.S
    )


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[GraphStore]:
    store = GraphStore()
    _dittrich(store)
    _store_snapshot(store, _pages(), "2026-09-30")
    cli("normalize", "eerstekamer-composition")
    yield store


def _members(store: GraphStore) -> dict[str, dict[str, Any]]:
    return {
        row["ek"]["path"]: row
        for row in store.query(
            "SELECT key, props -> 'ek' AS ek FROM members"
            " WHERE coalesce(json_typeof(props -> 'ek'), 'null') <> 'null'"
        )
    }


def test_a_snapshot_makes_the_factions_committees_and_members(
    store: GraphStore, cli: Any
) -> None:
    faction = present(store.get_document("factions", "ek_democraten_1966"))["props"]
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
    committee = present(store.get_document("committees", "ek_fin"))["props"]
    assert (committee["slug"], committee["abbreviation"]) == ("ek-fin", "FIN")

    # a week later Croll is no longer shown: observed until that day, the others unchanged
    _second_snapshot(store)
    cli("normalize", "eerstekamer-composition")
    members = _members(store)
    assert members[CROLL]["ek"]["observed_until"] == "2026-10-07"
    # the first snapshot stays the start of what is known
    faction = present(store.get_document("factions", "ek_democraten_1966"))["props"]
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


def _second_snapshot(store: GraphStore) -> None:
    """2026-10-07: Croll no longer on the page of D66."""
    pages = _pages()
    pages["/fractie/democraten_1966"] = _without_croll(
        pages["/fractie/democraten_1966"]
    )
    _store_snapshot(store, pages, "2026-10-07")


def test_a_page_is_stored_again_only_when_it_changed(store: GraphStore) -> None:
    """A page read again unchanged adds no version, only the day it was read last."""
    first = _versions(store)
    assert set(first) == {f"{path}@2026-09-30" for path in _pages()}

    _store_snapshot(store, _pages(), "2026-10-01")
    assert _versions(store) == dict.fromkeys(first, ("2026-09-30", "2026-10-01"))

    _second_snapshot(store)
    versions = _versions(store)
    assert len(versions) == len(first) + 1
    assert versions["/fractie/democraten_1966@2026-10-07"] == (
        "2026-10-07",
        "2026-10-07",
    )
    assert versions["/fracties@2026-09-30"] == ("2026-09-30", "2026-10-07")


def test_a_rebuild_from_raw_gives_the_same_periods(store: GraphStore, cli: Any) -> None:
    """The periods follow from the stored versions alone: normalizing them on an empty graph
    gives the composition the runs one after the other gave."""
    _second_snapshot(store)
    cli("normalize", "eerstekamer-composition")
    walked = normalize_tk.ek_composition(store)
    assert _members(store)[CROLL]["ek"]["observed_until"] == "2026-10-07"

    _empty_graph(store)
    cli("normalize", "eerstekamer-composition")

    assert normalize_tk.ek_composition(store) == walked


def test_the_observed_composition_keeps_periods_raw_no_longer_holds(
    store: GraphStore, cli: Any
) -> None:
    """``retrieve eerstekamer-composition-observed`` stores the composition of the graph
    once; a rebuild walks the versions after it from there, so periods whose pages raw lacks
    are kept."""
    _second_snapshot(store)
    cli("normalize", "eerstekamer-composition")
    walked = normalize_tk.ek_composition(store)
    cli("retrieve", "eerstekamer-composition-observed")
    cli(
        "retrieve", "eerstekamer-composition-observed"
    )  # once: the second stores nothing
    observed = list(
        store.query(
            "SELECT doc -> 'payload_json' -> 'covers' AS covers FROM raw_sources"
            " WHERE kind = 'ek-composition-observed'"
        )
    )
    assert len(observed) == 1 and len(observed[0]) == len(_pages()) + 1

    # the versions of 2026-09-30 are gone: only the composition observed holds that day
    store.execute(
        "DELETE FROM raw_sources WHERE kind = %(kind)s"
        " AND doc -> 'meta' ->> 'read_on' = '2026-09-30'",
        {"kind": RAW_KIND_EERSTEKAMER_COMPOSITION},
    )
    _empty_graph(store)
    cli("normalize", "eerstekamer-composition")
    assert normalize_tk.ek_composition(store) == walked

    # a later version is walked on top of it
    pages = _pages()
    _store_snapshot(store, pages, "2026-10-14")  # Croll is back
    cli("normalize", "eerstekamer-composition")
    croll = _members(store)[CROLL]["ek"]
    assert (croll["observed_from"], croll["observed_until"]) == ("2026-10-14", None)
    faction = present(store.get_document("factions", "ek_democraten_1966"))["props"]
    assert (faction["observed_from"], faction["data_since"]) == (
        "2026-09-30",
        "2026-09-30",
    )


def test_the_api_shows_the_eerste_kamer_beside_the_tweede(store: GraphStore) -> None:
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
        # where Wie zit waar seats him: the right block, third row, by the aisle but one
        assert dittrich["ek"]["seat"] == {"block": "right", "row": 2, "column": 2}
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
        # the colour the Eerste Kamer draws D66 in (Wie zit waar)
        assert seats["factions"][0]["colors"] == ["#00D84B"]
        # the hall: the seats of the members this snapshot knows, in the order of the plan
        hall = seats["hall"]
        assert hall["url"] == "https://www.eerstekamer.nl/wie_zit_waar"
        assert [(p["block"], p["row"], p["column"]) for p in hall["seats"]] == [
            ("right", 1, 1),
            ("right", 1, 2),
            ("right", 1, 3),
            ("right", 2, 0),
            ("right", 2, 1),
            ("right", 2, 2),
            ("right", 2, 3),
        ]
        assert hall["seats"][5] == {
            "block": "right",
            "row": 2,
            "column": 2,
            "faction": "ek_democraten_1966",
            "abbreviation": "D66",
            "member": "dittrich",
            "name": "mr. B.O. Dittrich",
        }
        assert (
            client.get(
                "/api/parliament/seats", params={"chamber": "EK", "date": "2026-01-01"}
            ).status_code
            == 404  # no stretch of that day is known
        )
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_hall_on_a_day_is_the_plan_read_since(store: GraphStore) -> None:
    """Wie zit waar shows today's plan only: a day from the day it was read gets it, a day
    before it gets none, and the response says from which day the plan is known."""
    ek_seats.write(
        store,
        [
            {
                "start": "2023-06-13",
                "election": "2023-05-30",
                "source": {},
                "checked": True,
                "mismatches": [],
            }
        ],
        [
            {
                "from_date": "2023-06-13",
                "to_date": None,
                "term": "2023-06-13",
                "seats": {"D66": 7},
                "events": [],
            }
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)

        def seats(**params: str) -> dict[str, Any]:
            response = client.get("/api/parliament/seats", params=params)
            assert response.status_code == 200
            return dict(response.json())

        today = seats(chamber="EK")
        on_read = seats(chamber="EK", date="2026-09-30")
        later = seats(chamber="EK", date="2026-10-05")
        before = seats(chamber="EK", date="2026-09-29")
        tk = seats()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert today["hall_read_on"] == "2026-09-30"
    assert on_read["hall"] == today["hall"] == later["hall"]
    assert len(on_read["hall"]["seats"]) == 7
    assert (before["hall"], before["hall_read_on"]) == (None, "2026-09-30")
    # the Tweede Kamer publishes no plan of its seats as data
    assert (tk["hall"], tk["hall_read_on"]) == (None, None)
