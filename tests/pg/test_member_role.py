"""Whether a member has a role, in SQL as in Python (``db.queries.member_role``), and what the
member detail and search make of it."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.core.member_role import has_role
from lawgraph.db import GraphStore
from lawgraph.db.queries import member_role
from lawgraph.db.queries import search as search_queries
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
