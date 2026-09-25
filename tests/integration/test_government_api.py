"""Cabinets, bewindspersonen and commitments: the real ``normalize rijksoverheid`` and
``semantic tk-government`` on the stored pages of Schoof and Jetten, and the endpoints on
their answer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_CABINETS,
    COLLECTION_COMMITMENTS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RAW_KIND_WIKIDATA_CABINET,
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_PART_OF,
    RELATION_SERVED_IN,
    SOURCE_RIJKSOVERHEID,
    SOURCE_WIKIDATA,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import (
    ArangoStore,
    EdgeWriter,
    NodeWriter,
    RawSourceWriter,
    raw_source_doc,
)

PAGES = Path(__file__).parents[1] / "fixtures" / "rijksoverheid"
# A cabinet before the first page: from Wikidata, name and period only.
RUTTE_IV = {
    "id": "Q110111120",
    "name": "kabinet-Rutte IV",
    "from_date": "2022-01-10",
    "from_date_precision": 11,
    "to_date": "2024-07-02",
    "to_date_precision": 11,
    "previous": [],
}


def _node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=["TK"], props=props
    )


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


def _seed(store: ArangoStore) -> None:
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
                    track_kind="wetsvoorstel",
                    opened_on="2026-09-15",
                    current_stage="mvt",
                ),
                _node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "37100",
                    number="37100",
                    label="37100",
                    title="Initiatiefwet",
                    track_kind="initiatiefwetsvoorstel",
                    opened_on="2026-05-01",
                    current_stage="wetsvoorstel",
                ),
                _node(
                    COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "bill", date="2026-09-15"
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
                    status="open",
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
                    status="open",
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
        writer.add(
            raw_source_doc(
                source=SOURCE_WIKIDATA,
                kind=RAW_KIND_WIKIDATA_CABINET,
                external_id=RUTTE_IV["id"],
                payload_json=RUTTE_IV,
            )
        )


def _client(store: ArangoStore) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_cabinets_their_bewindspersonen_and_commitments(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _seed(store)

    cli("normalize", "rijksoverheid")
    cli("semantic", "tk-government")

    jetten = store.get_node(COLLECTION_CABINETS, "jetten")
    assert jetten is not None
    assert jetten.props["name"] == "kabinet-Jetten"
    assert jetten.props["prime_minister"] == "jetten"
    assert jetten.props["previous"] == "schoof"
    assert [p["short"] for p in jetten.props["parties"]] == ["D66", "VVD", "CDA"]
    assert jetten.props["factions"] == ["d66", "vvd"]
    served = list(
        store.query(
            "FOR e IN edges FILTER e.relation == @r AND e._from == @m RETURN e._to",
            {"r": RELATION_SERVED_IN, "m": f"{COLLECTION_MEMBERS}/heinen"},
        )
    )
    assert sorted(served) == ["cabinets/jetten", "cabinets/schoof"]

    try:
        client = _client(store)
        cabinets = client.get("/api/cabinets").json()
        detail = client.get("/api/cabinets/jetten").json()
        schoof = client.get("/api/cabinets/schoof").json()
        ministers = client.get("/api/members?cabinet=jetten").json()
        everyone = client.get("/api/members?include_all=true").json()
        commitments = client.get(
            "/api/commitments?ministry=fin&sort=expected_resolution"
        ).json()
        overdue = client.get("/api/commitments?overdue=true").json()
        by_dossier = client.get("/api/commitments?dossier=37022").json()
        dossiers = client.get("/api/dossiers/open?ministry=fin").json()
        initiatives = client.get("/api/dossiers/open?initiative=true").json()
        missing = client.get("/api/cabinets/nope").status_code
        unknown_ministry = client.get("/api/commitments?ministry=nope").status_code
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert [c["key"] for c in cabinets] == ["jetten", "schoof", "rutte_iv"]
    assert cabinets[0]["prime_minister"] == {
        "key": "jetten",
        "name": "Rob Arnoldus Adrianus Jetten",
    }
    assert (cabinets[0]["bills"], cabinets[0]["commitments"]) == (1, 2)
    assert cabinets[0]["members"] >= 25
    # before the first page: Wikidata, name and period only
    assert (
        cabinets[2]["source"]["name"],
        cabinets[2]["phases"],
        cabinets[2]["parties"],
    ) == (
        "wikidata",
        [],
        [],
    )
    assert cabinets[2]["to_date"] == "2024-07-02"

    # the phases of Schoof, and its seats: a stand-in between two holders
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

    # the minister-president first, then the ministries in protocol order
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

    assert commitments["total"] == 2
    first = commitments["items"][0]
    assert first["key"] == "toezegging"  # due first; the undated one last
    assert first["member"] == {
        "key": "heinen",
        "name": "Eelco Heinen",
        "function": "Minister van Financiën",
    }
    assert (first["cabinet"], first["post"]) == ("jetten", "minister")
    assert [d["number"] for d in first["dossiers"]] == ["37022"]
    assert commitments["items"][1]["expected_resolution"] is None
    assert [c["key"] for c in overdue["items"]] == ["toezegging"]
    assert by_dossier["total"] == 1

    assert [d["number"] for d in dossiers["items"]] == ["37022"]
    assert dossiers["items"][0]["ministry"] == "fin"
    assert dossiers["items"][0]["cabinet"] == "jetten"
    # each dimension counted without its own filter: the initiative stays in the track facet
    assert {f["value"]: f["count"] for f in dossiers["facets"]["ministry"]} == {
        None: 1,
        "fin": 1,
    }
    assert {f["value"]: f["count"] for f in dossiers["facets"]["track"]} == {
        "wetsvoorstel": 1
    }
    assert [d["number"] for d in initiatives["items"]] == ["37100"]
    assert (missing, unknown_ministry) == (404, 422)
