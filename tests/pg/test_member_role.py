"""Whether a member has a role, in SQL as in Python (``db.queries.member_role``), and what the
member detail and search make of it."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RAW_KIND_TK_PERSOON, SOURCE_TK
from lawgraph.core.member_role import has_role
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries import member_role
from lawgraph.db.queries import search as search_queries
from lawgraph.pipelines.normalize.tk_dossiers import TKDossiersNormalizePipeline
from tests.test_member_role import CASES


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "member", "labels": [], "props": props}


def test_the_sql_is_the_python(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "members", [_node(f"m_{i}", **props) for i, (props, _) in enumerate(CASES)]
    )
    found = {
        row["key"]: row["role"]
        for row in store.query(
            f"SELECT m.key, {member_role.has_role('m')} AS role FROM members m"
        )
    }
    assert found == {f"m_{i}": has_role(props) for i, (props, _) in enumerate(CASES)}


def test_search_and_the_detail(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "members",
        [
            # a person of the TK's records whose seat the data does not hold
            _node("vries_1", name="J. de Vries", slug="j-de-vries",
                  birth_date="1924-04-28", death_date="2009-01-05"),
            _node("vries_2", name="Jan de Vries", slug="jan-de-vries",
                  faction_memberships=[{"faction_id": "factions/cda", "faction_key": "cda",
                                       "from_date": "2002-05-23"}]),
        ],
    )  # fmt: skip
    hits = search_queries.search_all(store, q="de Vries", types=["members"])["members"]
    assert [(h["key"], h["extra"]["has_role"]) for h in hits] == [
        ("vries_2", True),
        ("vries_1", False),
    ]

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        alone = client.get("/api/members/vries_1").json()
        assert (alone["has_role"], alone["birth_date"], alone["death_date"]) == (
            False,
            "1924-04-28",
            "2009-01-05",
        )
        assert client.get("/api/members/vries_2").json()["has_role"] is True
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_persons_again_give_the_day_they_died(store: GraphStore) -> None:
    """``normalize tk-dossiers --persons``: every stored Persoon record into its member,
    merged into what other steps wrote (their seats stay)."""
    person = "b153ff84-388e-41a4-a0d9-e1be6dc00d04"
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node(make_node_key(person), external_id=person, name="P.J.H.M. Luijten",
                  slug="p-j-h-m-luijten",
                  faction_memberships=[{"faction_id": "factions/vvd", "faction_key": "vvd"}]),
        ],
    )  # fmt: skip
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_PERSOON,
                external_id=person,
                payload_json={
                    "Id": person,
                    "Initialen": "PJHM",
                    "Achternaam": "Luijten",
                    "Geboortedatum": "1924-04-28T00:00:00",
                    "Overlijdensdatum": "2009-01-05T00:00:00",
                    "Verwijderd": False,
                },
            )
        )
    TKDossiersNormalizePipeline(store, persons=True).run()
    props = store.get_document("members", make_node_key(person))["props"]
    assert props["death_date"] == "2009-01-05"
    assert props["faction_memberships"][0]["faction_key"] == "vvd"
    assert props["slug"] == "p-j-h-m-luijten"
