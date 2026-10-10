"""The periods of the members of the Eerste Kamer in its factions (``normalize
eerstekamer-persons``) on a real PostgreSQL, from their real pages: to the member the
composition gave the page, else to the member of the Tweede Kamer born that day whose surname
ends its name; none for a former member without a member; read with the periods of the
Tweede Kamer by the page of a member's votes, and in the member's detail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_EK_PERSON,
    RELATION_VOTED,
    SOURCE_EERSTEKAMER,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import faction_votes
from lawgraph.db.queries.committees import get_member_votes
from lawgraph.db.store import raw_source_doc
from lawgraph.pipelines.normalize.eerstekamer_persons import (
    EerstekamerPersonsNormalizePipeline,
)
from tests.pg.test_committees_queries import Graph

EK = Path(__file__).resolve().parents[1] / "fixtures" / "eerstekamer"
DITTRICH = "/persoon/mr_b_o_dittrich_d66"
OTTEN = "/persoon/mr_drs_h_otten_fractie_otten"
DUTHLER = "/persoon/mr_dr_a_w_duthler_fractie_duthler"
TK_D66 = {"faction_id": "factions/d66", "faction_key": "d66", "abbreviation": "D66",
          "from_date": "2003-01-30", "to_date": "2006-11-29"}  # fmt: skip


def _pages(store: GraphStore, paths: list[str]) -> None:
    store.insert_raw_sources(
        [
            raw_source_doc(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_PERSON,
                external_id=path,
                payload_text=(EK / f"persoon_{path.rsplit('/', 1)[1]}.html").read_text(
                    "utf-8"
                ),
            )
            for path in paths
        ]
    )


def _graph(store: GraphStore, **member: Any) -> None:
    g = Graph(store)
    g.node("factions", "ek_d66", name="Democraten 66", abbreviation="D66", chamber="EK",
           observed_from="2023-06-13")  # fmt: skip
    g.node("factions", "d66", name="D66", abbreviation="D66")
    g.node("members", "dittrich", name="Boris Dittrich", **member)
    g.write()


def _periods(store: GraphStore, key: str) -> Any:
    (row,) = store.query(
        "SELECT props -> 'ek_faction_memberships' AS p FROM members WHERE key = %(k)s",
        {"k": key},
    )
    return row


def test_a_page_goes_to_the_member_the_composition_gave_it(store: GraphStore) -> None:
    _graph(store, ek={"path": DITTRICH}, faction_memberships=[TK_D66])
    _pages(store, [DITTRICH, OTTEN, DUTHLER])
    EerstekamerPersonsNormalizePipeline(store=store).run()
    # Otten and Duthler: former members without a member, written to none
    with_periods = store.query(
        "SELECT key FROM members WHERE props -> 'ek_faction_memberships' IS NOT NULL"
    )
    assert list(with_periods) == ["dittrich"]
    assert _periods(store, "dittrich") == [
        {
            "faction_id": "factions/ek_d66",
            "faction_key": "ek_d66",
            "abbreviation": "D66",
            "name": "Democraten 66",
            "from_date": "2019-06-11",
            "to_date": None,
            "chamber": "EK",
        }
    ]


def test_else_to_the_member_of_the_tweede_kamer_born_that_day(
    store: GraphStore,
) -> None:
    _graph(store, family_name="Dittrich", birth_date="1955-07-21")
    _pages(store, [DITTRICH])
    EerstekamerPersonsNormalizePipeline(store=store).run()
    assert _periods(store, "dittrich")[0]["from_date"] == "2019-06-11"


def test_a_member_of_both_chambers_has_the_votes_of_both_factions(
    store: GraphStore,
) -> None:
    """Their faction of the Tweede Kamer then, of the Eerste Kamer now: both on the page of
    their votes, and their periods of the Eerste Kamer in their detail."""
    _graph(store, ek={"path": DITTRICH}, faction_memberships=[TK_D66])
    g = Graph(store)
    g.node("decisions", "tk1", date="2005-03-01")
    g.node("decisions", "ek1", date="2024-05-14", chamber="EK")
    g.edge("factions/d66", RELATION_VOTED, "decisions/tk1", choice="Voor", seats=6)
    g.edge("factions/ek_d66", RELATION_VOTED, "decisions/ek1", choice="Tegen", seats=5)
    g.write()
    _pages(store, [DITTRICH])
    walked_before = get_member_votes(store, "members/dittrich")
    assert [v["decision_key"] for v in walked_before] == ["tk1"]
    EerstekamerPersonsNormalizePipeline(store=store).run()
    walked = get_member_votes(store, "members/dittrich")
    assert [(v["decision_key"], v["faction_key"], v["party"]) for v in walked] == [
        ("ek1", "ek_d66", "D66"),
        ("tk1", "d66", "D66"),
    ]
    faction_votes.fill_faction_votes(store)
    assert get_member_votes(store, "members/dittrich") == walked

    app.dependency_overrides[get_store] = lambda: store
    try:
        detail = TestClient(app).get("/api/members/dittrich").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert detail["ek_faction_memberships"][0]["abbreviation"] == "D66"
    assert detail["ek_faction_memberships"][0]["from_date"] == "2019-06-11"


def test_the_pages_to_fetch(store: GraphStore) -> None:
    """Every sitting member's and every person a change links, once; again when a change
    that links them was fetched after their page; every sitting member's with ``sitting``."""
    from lawgraph.config.constants import RAW_KIND_EK_COMPOSITION, RAW_KIND_EK_MUTATION
    from lawgraph.pipelines.retrieve.eerstekamer_persons import (
        EerstekamerPersonsRetrievePipeline,
    )

    def change(path: str, person: str, at: str) -> dict[str, Any]:
        page = f'<main>Nieuwsoverzicht <a href="{person}">X</a> Terug naar boven</main>'
        doc = raw_source_doc(source=SOURCE_EERSTEKAMER, kind=RAW_KIND_EK_MUTATION,
                             external_id=path, payload_text=page)  # fmt: skip
        return {**doc, "fetched_at": at}

    def person(path: str) -> dict[str, Any]:
        doc = raw_source_doc(source=SOURCE_EERSTEKAMER, kind=RAW_KIND_EK_PERSON,
                             external_id=path, payload_text="<html></html>")  # fmt: skip
        return {**doc, "fetched_at": "2026-10-01T00:00:00+00:00"}

    faction = (EK / "fractie_progressief_nederland_pro.html").read_text("utf-8")
    store.insert_raw_sources(
        [
            raw_source_doc(source=SOURCE_EERSTEKAMER, kind=RAW_KIND_EK_COMPOSITION,
                           external_id="/fractie/progressief_nederland_pro",
                           payload_text=faction),
            change("/nieuws/1", OTTEN, "2026-09-01T00:00:00+00:00"),
        ]
    )  # fmt: skip

    def wanted(**options: Any) -> list[str]:
        return EerstekamerPersonsRetrievePipeline(store, object(), **options).wanted()  # type: ignore[arg-type]

    every = wanted()
    sitting = [p for p in every if p != OTTEN]
    assert OTTEN in every and len(sitting) == 14  # the faction's members

    store.insert_raw_sources([person(p) for p in every])
    assert wanted() == []
    assert wanted(sitting=True) == sitting
    # a change fetched after Otten's page links him: his page again
    store.insert_raw_sources([change("/nieuws/2", OTTEN, "2026-10-05T00:00:00+00:00")])
    assert wanted() == [OTTEN]
