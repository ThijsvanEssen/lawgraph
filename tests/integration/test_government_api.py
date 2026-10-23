"""Cabinets, bewindspersonen and commitments: the real ``normalize rijksoverheid`` and
``semantic tk-government`` on the stored pages of Schoof and Jetten, and the endpoints on
their answer."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_MEMBERS,
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_PART_OF,
    RELATION_SERVED_IN,
    SOURCE_RIJKSOVERHEID,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import (
    EdgeWriter,
    GraphStore,
    NodeWriter,
    RawSourceWriter,
    raw_source_doc,
)
from tests.asserts import assert_status
from tests.databases import Api, ModuleStore, module_store

PAGES = Path(__file__).parents[1] / "fixtures" / "rijksoverheid"


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(collection=collection, key=key, labels=["TK"], props=props)


def _member(key: str, name: str, family_name: str, birth_date: str) -> Node:
    """A member of parliament: the full first names, by whose initials a holder is found."""
    return _node(
        COLLECTION_MEMBERS,
        NodeType.MEMBER,
        key,
        name=name,
        family_name=family_name,
        birth_date=birth_date,
    )


def _seed(store: GraphStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _member(
                    "jetten", "Rob Arnoldus Adrianus Jetten", "Jetten", "1987-03-25"
                ),
                _member("heinen", "Eelco Heinen", "Heinen", "1981-01-02"),
                _member(
                    "sjoerdsma", "Sjoerd Wiebren Sjoerdsma", "Sjoerdsma", "1981-05-05"
                ),
                _member("aartsen", "Anthonie Arie Aartsen", "Aartsen", "1983-06-06"),
                _member("kamerlid", "Kim Kamerlid", "Kamerlid", "1990-01-01"),
                # a Tweede Kamer person without a name is never listed
                _node(COLLECTION_MEMBERS, NodeType.MEMBER, "nameless", name=""),
                _node(
                    COLLECTION_FACTIONS,
                    NodeType.FACTION,
                    "vvd",
                    name="Volkspartij voor Vrijheid en Democratie",
                    abbreviation="VVD",
                ),
                _node(
                    COLLECTION_FACTIONS,
                    NodeType.FACTION,
                    "d66",
                    name="Democraten 66",
                    abbreviation="D66",
                ),
                _node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "37022",
                    number="37022",
                    label="37022",
                    title="Belastingplan 2027",
                    kind="Wetgeving",
                    opened_on="2026-09-15",
                    current_phase="Memorie van toelichting",
                ),
                _node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "37100",
                    number="37100",
                    label="37100",
                    title="Initiatiefwet",
                    kind="Initiatiefwetgeving",
                    opened_on="2026-05-01",
                    current_phase="Voorstel van wet",
                ),
                _node(
                    COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "bill", date="2026-09-15"
                ),
                # the WTI names its first responsible ministry (``normalize bwb``)
                *(
                    _node(
                        COLLECTION_INSTRUMENTS,
                        NodeType.INSTRUMENT,
                        bwb_id.lower(),
                        bwb_id=bwb_id,
                        kind="wet",
                        citation_title=title,
                        ministry=ministry,
                    )
                    for bwb_id, title, ministry in (
                        ("BWBR0009508", "Bankwet 1998", "fin"),
                        ("BWBR0011823", "Vreemdelingenwet 2000", "jenv"),
                    )
                ),
                _node(
                    COLLECTION_DOCUMENTS,
                    NodeType.DOCUMENT,
                    "initiative",
                    date="2026-05-01",
                ),
                _node(
                    COLLECTION_COMMITMENTS,
                    NodeType.COMMITMENT,
                    "toezegging",
                    text="De minister stuurt de Kamer een brief over de box 3.",
                    minister_name="Heinen, E.",
                    minister_role="Minister van Financiën",
                    made_on="2026-04-01",
                    expected_resolution="2026-05-01",
                    status="Openstaand",
                ),
                _node(
                    COLLECTION_COMMITMENTS,
                    NodeType.COMMITMENT,
                    "undated",
                    text="Een toezegging zonder termijn.",
                    minister_name="Heinen, E.",
                    minister_role="Minister van Financiën",
                    made_on="2026-04-02",
                    expected_resolution="0001-01-01",
                    status="Openstaand",
                ),
            ]
        )
    with EdgeWriter(store, what=None) as edges:
        for document, dossier in (("bill", "37022"), ("initiative", "37100")):
            edges.add(
                f"{COLLECTION_DOCUMENTS}/{document}",
                f"{COLLECTION_DOSSIERS}/{dossier}",
                RELATION_PART_OF,
                source="t",
            )
        edges.add(
            f"{COLLECTION_MEMBERS}/heinen",
            f"{COLLECTION_DOCUMENTS}/bill",
            RELATION_AUTHORED,
            source="t",
            meta={
                "role": "Eerste ondertekenaar",
                "capacity": "bewindspersoon",
                "function": "minister van Financiën",
            },
        )
        edges.add(
            f"{COLLECTION_MEMBERS}/kamerlid",
            f"{COLLECTION_DOCUMENTS}/initiative",
            RELATION_AUTHORED,
            source="t",
            meta={
                "role": "Eerste ondertekenaar",
                "capacity": "kamerlid",
                "function": "Tweede Kamerlid",
            },
        )
        edges.add(
            f"{COLLECTION_COMMITMENTS}/toezegging",
            f"{COLLECTION_DOSSIERS}/37022",
            RELATION_ABOUT,
            source="t",
        )
    with RawSourceWriter(store) as writer:
        for slug in ("kabinet-schoof", "kabinet-jetten"):
            writer.add(
                raw_source_doc(
                    source=SOURCE_RIJKSOVERHEID,
                    kind=RAW_KIND_RIJKSOVERHEID_CABINET,
                    external_id=slug,
                    payload_text=(PAGES / f"{slug}.html").read_text(),
                    meta={
                        "url": f"https://example.org/{slug}",
                        "read_on": "2026-09-25",
                    },
                )
            )


# The tests read one database built for them all (``world``), on the worker that built it.
pytestmark = pytest.mark.xdist_group("government_api")


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleStore]:
    """The cabinets built once for every test here, on a database of its own: the real
    ``normalize rijksoverheid`` and ``semantic tk-government``; the tests read it (one runs
    ``semantic tk-government`` again and finds it unchanged)."""
    with module_store(tmp_path_factory) as world:
        _seed(world.store)
        world.cli("normalize", "rijksoverheid")
        world.cli("semantic", "tk-government")
        world.cli("semantic", "tooi-ministries")
        yield world


@pytest.fixture(scope="module")
def store(world: ModuleStore) -> GraphStore:
    return world.store


def test_cabinets_their_bewindspersonen_and_commitments_are_written(
    world: ModuleStore,
) -> None:
    store, cli = world
    jetten = store.get_node(COLLECTION_CABINETS, "jetten")
    assert jetten is not None
    assert jetten.props["name"] == "kabinet-Jetten"
    assert jetten.props["prime_minister"] == "jetten"
    assert jetten.props["previous"] == "schoof"
    assert [p["short"] for p in jetten.props["parties"]] == ["D66", "VVD", "CDA"]
    assert jetten.props["factions"] == ["d66", "vvd"]
    served = list(
        store.query(
            "SELECT to_id FROM edges WHERE relation = %(r)s AND from_id = %(m)s"
            " AND to_collection = 'cabinets'",
            {"r": RELATION_SERVED_IN, "m": f"{COLLECTION_MEMBERS}/heinen"},
        )
    )
    assert sorted(served) == ["cabinets/jetten", "cabinets/schoof"]
    # who made each commitment, as an edge: Heinen, as toezegger, to both of his
    made = {
        (row["to_id"], row["role"])
        for row in store.query(
            "SELECT to_id, doc -> 'meta' ->> 'role' AS role FROM edges"
            " WHERE relation = 'AUTHORED' AND from_id = %(m)s"
            " AND to_collection = 'commitments'",
            {"m": f"{COLLECTION_MEMBERS}/heinen"},
        )
    }
    assert {role for _, role in made} == {"toezegger"} and len(made) == 2
    # a second run writes nothing new and removes nothing
    cli("semantic", "tk-government")
    assert (
        len(
            list(
                store.query(
                    "SELECT 1 FROM edges WHERE relation = 'AUTHORED'"
                    " AND to_collection = 'commitments'"
                )
            )
        )
        == 2
    )


def test_the_cabinets_newest_first_with_their_counts(
    api: Api,
) -> None:
    cabinets = api.get_json("/api/cabinets")
    assert [c["key"] for c in cabinets] == ["jetten", "schoof"]
    assert cabinets[0]["prime_minister"] == {
        "key": "jetten",
        "name": "Rob Arnoldus Adrianus Jetten",
        "path": "/leden/rob-arnoldus-adrianus-jetten",
    }
    assert (cabinets[0]["bills"], cabinets[0]["commitments"]) == (1, 2)
    assert cabinets[0]["members"] >= 25


def test_a_cabinet_has_its_phases_and_a_stand_in_between_two_holders(
    api: Api,
) -> None:
    schoof = api.get_json("/api/cabinets/schoof")
    assert schoof["demissionary_from"] == "2025-06-03"
    assert [(p["kind"], p["from_date"]) for p in schoof["phases"]] == [
        ("formatie", "2023-11-22"),
        ("in_functie", "2024-07-02"),
        ("demissionair", "2025-06-03"),
        ("dubbel_demissionair", "2025-08-22"),
    ]
    assert schoof["source"]["url"] == "https://example.org/kabinet-schoof"
    ez = next(m for m in schoof["ministries"] if m["ministry"] == "ez")
    (minister,) = [s for s in ez["seats"] if s["seat"] == "ez/minister"]
    assert [
        (p["member"]["key"] == "heinen", p["from_date"], p["acting"])
        for p in minister["posts"]
    ] == [
        (False, "2024-07-02", False),
        (True, "2025-06-03", True),
        (False, "2025-06-19", False),
    ]
    assert minister["posts"][1]["party"] == {"short": "VVD", "faction": "vvd"}


def test_a_cabinet_has_the_minister_president_first_then_protocol_order(
    api: Api,
) -> None:
    detail = api.get_json("/api/cabinets/jetten")
    ministries = [m["ministry"] for m in detail["ministries"]]
    assert ministries[:3] == ["az", "bz", "jenv"]
    fin = next(m for m in detail["ministries"] if m["ministry"] == "fin")
    heinen = fin["seats"][0]["posts"][0]
    assert (
        heinen["member"]["key"],
        heinen["post"],
        heinen["dossiers"],
        heinen["bills"],
        heinen["open_commitments"],
    ) == ("heinen", "minister", 1, 1, 2)


def test_the_members_of_a_cabinet_with_their_government_functions(
    api: Api,
) -> None:
    ministers = api.get_json("/api/members?cabinet=jetten")
    everyone = api.get_json("/api/members?include_all=true")
    assert {"aartsen", "heinen", "jetten", "sjoerdsma"} <= {m["key"] for m in ministers}
    heinen_functions = next(m for m in ministers if m["key"] == "heinen")[
        "government_functions"
    ]
    assert [(f["cabinet_key"], f["seat"], f["acting"]) for f in heinen_functions] == [
        ("schoof", "fin/minister", False),
        ("schoof", "ez/minister", True),
        ("jetten", "fin/minister", False),
    ]
    assert "nameless" not in {m["key"] for m in everyone}


def test_the_commitments_of_a_ministry_overdue_or_of_a_dossier(
    api: Api,
) -> None:
    commitments = api.get_json("/api/commitments?ministry=fin&sort=expected_resolution")
    overdue = api.get_json("/api/commitments?overdue=true")
    by_dossier = api.get_json("/api/commitments?dossier=37022")
    assert commitments["total"] == 2
    # counted without their own filter; only values that have commitments
    assert commitments["facets"]["ministry"] == [{"value": "fin", "count": 2}]
    assert commitments["facets"]["cabinet"] == [{"value": "jetten", "count": 2}]
    assert commitments["facets"]["status"] == [{"value": "Openstaand", "count": 2}]
    first = commitments["items"][0]
    assert first["key"] == "toezegging"  # due first; the undated one last
    assert first["member"] == {
        "key": "heinen",
        "name": "Eelco Heinen",
        "function": "Minister van Financiën",
        "path": "/leden/eelco-heinen",
    }
    assert (first["cabinet"], first["post"]) == ("jetten", "minister")
    assert [d["number"] for d in first["dossiers"]] == ["37022"]
    assert commitments["items"][1]["expected_resolution"] is None
    assert [c["key"] for c in overdue["items"]] == ["toezegging"]
    assert by_dossier["total"] == 1


def test_the_open_dossiers_of_a_ministry_or_of_the_members(
    api: Api,
) -> None:
    dossiers = api.get_json("/api/dossiers?status=open&ministry=fin")
    initiatives = api.get_json("/api/dossiers?status=open&initiative=true")
    assert [d["number"] for d in dossiers["items"]] == ["37022"]
    assert dossiers["items"][0]["ministry"] == "fin"
    assert dossiers["items"][0]["cabinet"] == "jetten"
    # each dimension counted without its own filter: the initiative stays in the kind facet
    assert {f["value"]: f["count"] for f in dossiers["facets"]["ministry"]} == {
        None: 1,
        "fin": 1,
    }
    assert {f["value"]: f["count"] for f in dossiers["facets"]["kind"]} == {
        "Wetgeving": 1
    }
    assert [d["number"] for d in initiatives["items"]] == ["37100"]


def test_an_unknown_cabinet_is_404_and_an_unknown_ministry_422(
    api: Api,
) -> None:
    missing = api.get("/api/cabinets/nope").status_code
    unknown_ministry = api.get("/api/commitments?ministry=nope").status_code
    assert (missing, unknown_ministry) == (404, 422)


def test_a_ministry_with_its_bewindspersonen_and_what_is_its_own(api: Api) -> None:
    fin = api.get_json("/api/ministries/fin")
    ez = api.get_json("/api/ministries/ez")
    jenv = api.get_json("/api/ministries/jenv")
    assert fin["name"] == "Financiën"
    assert [c["key"] for c in fin["cabinets"]] == ["jetten", "schoof"]  # newest first
    (heinen,) = [p for p in fin["cabinets"][0]["posts"] if p["post"] == "minister"]
    assert (heinen["member"]["key"], heinen["member"]["path"]) == (
        "heinen",
        "/leden/eelco-heinen",
    )
    assert (fin["laws"], fin["open_dossiers"], fin["open_commitments"]) == (1, 1, 2)
    # a post stands under the ministry of its day: Heinen as acting minister of EZ
    acting = [
        p["member"]["key"] for c in ez["cabinets"] for p in c["posts"] if p["acting"]
    ]
    assert acting == ["heinen"]
    assert jenv["predecessors"] == ["venj"]
    assert_status(api.get("/api/ministries/nope"), 404)


def test_a_law_a_dossier_and_a_commitment_name_their_ministry(api: Api) -> None:
    laws = api.get_json("/api/instruments?ministry=fin")
    law = api.get_json("/api/instruments/BWBR0009508")
    dossiers = api.get_json("/api/dossiers?status=open&ministry=fin")
    commitments = api.get_json("/api/commitments?ministry=fin")
    named = [
        (item["ministry"], item["ministry_name"])
        for item in (
            *laws["items"],
            law,
            *dossiers["items"],
            *commitments["items"],
        )
    ]
    assert [i["bwb_id"] for i in laws["items"]] == ["BWBR0009508"]
    assert set(named) == {("fin", "Financiën")}
    assert len(named) == 5


def _edges_into(store: GraphStore, relation: str, to_id: str) -> list[str]:
    return sorted(
        store.query(
            "SELECT from_id FROM edges WHERE relation = %(r)s AND to_id = %(t)s",
            {"r": relation, "t": to_id},
        )
    )


def test_a_ministry_is_a_node_with_what_leads_to_it(world: ModuleStore) -> None:
    store, cli = world
    fin = store.get_node("ministries", "fin")
    assert fin is not None and fin.props["name"] == "Financiën"
    assert _edges_into(store, "LED_BY", "ministries/fin") == [
        "commitments/toezegging",
        "commitments/undated",
        "dossiers/37022",
        "instruments/bwbr0009508",
    ]
    assert _edges_into(store, "LED_BY", "ministries/jenv") == [
        "instruments/bwbr0011823"
    ]
    assert "members/heinen" in _edges_into(store, "SERVED_IN", "ministries/fin")
    posts = next(
        store.query(
            "SELECT doc -> 'meta' -> 'posts' FROM edges WHERE relation = 'SERVED_IN'"
            " AND from_id = 'members/heinen' AND to_id = 'ministries/ez'"
        )
    )
    assert [p["acting"] for p in posts] == [True]  # ad interim under EZ
    assert _edges_into(store, "CONTINUES", "ministries/venj") == ["ministries/jenv"]
    before = len(
        list(store.query("SELECT key FROM edges WHERE source = 'tooi-ministries'"))
    )
    cli("semantic", "tooi-ministries")  # a second run writes the same
    after = len(
        list(store.query("SELECT key FROM edges WHERE source = 'tooi-ministries'"))
    )
    assert after == before


def test_a_ministry_has_an_address_a_lookup_and_neighbours(api: Api) -> None:
    node = api.get_json("/api/nodes/ministries/fin")
    found = api.get_json("/api/lookup?kind=ministry&id=fin")
    listed = api.get_json("/api/ministries")
    assert found["id"] == "ministries/fin"
    assert found["path"] == "/ministeries/fin"
    assert next(m for m in listed if m["key"] == "fin")["path"] == "/ministeries/fin"
    assert (node["node"]["key"], node["path"], node["title"]) == (
        "fin",
        "/ministeries/fin",
        "Ministerie van Financiën",
    )
    buckets = {
        (b["relation"], b["direction"], b["collection"]): b["total"]
        for b in node["neighbors"]["buckets"]
    }
    assert buckets[("LED_BY", "inbound", "instruments")] == 1
    assert buckets[("SERVED_IN", "inbound", "members")] >= 1
