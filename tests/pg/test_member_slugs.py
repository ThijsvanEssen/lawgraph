"""The slugs of members on a real PostgreSQL: given once, found by ``/api/members?slug=``
and ``/api/lookup?kind=member``, and checked to be one per member."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.commands.check import Report, _check_member_slugs
from lawgraph.db import GraphStore
from lawgraph.db.queries.committees import get_members
from lawgraph.pipelines.normalize._member_slugs import assign_member_slugs

D66 = {"faction_key": "d66", "abbreviation": "D66", "from_date": "2017-03-23"}


def _member(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "member", "labels": ["TK"], "props": props}


def test_slugs_are_given_once_and_find_their_member(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _member("jetten", name="Rob Jetten", faction_memberships=[D66]),
            _member("vries_1", name="Jan de Vries", birth_date="1950-01-01"),
        ],
    )
    assert assign_member_slugs(store) == 2
    # a namesake read later: the first keeps the bare name
    store.bulk_insert_or_update_nodes(
        "members", [_member("vries_2", name="Jan de Vries", birth_date="1971-03-02")]
    )
    assert assign_member_slugs(store) == 1
    assert assign_member_slugs(store) == 0  # nothing to give again
    slugs = {
        m["_key"]: m["props"]["slug"] for m in get_members(store, include_all=True)
    }
    assert slugs == {
        "jetten": "rob-jetten",
        "vries_1": "jan-de-vries",
        "vries_2": "jan-de-vries-1971",
    }

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = client.get("/api/members", params={"slug": "Jan-De-Vries-1971"}).json()
        assert [m["key"] for m in listed] == ["vries_2"]
        assert listed[0]["slug"] == "jan-de-vries-1971"
        found = client.get("/api/lookup", params={"kind": "member", "id": "rob-jetten"})
        assert found.status_code == 200
        assert (found.json()["kind"], found.json()["key"]) == ("member", "jetten")
        assert found.json()["props"]["slug"] == "rob-jetten"
        missing = client.get("/api/lookup", params={"kind": "member", "id": "nobody"})
        assert (missing.status_code, missing.json()["detail"]) == (404, "not_in_data")
    finally:
        app.dependency_overrides.pop(get_store, None)

    report = Report()
    _check_member_slugs(store, report)
    assert not report.problems
    # two runs side by side: one slug of two members is a problem
    store.bulk_insert_or_update_nodes(
        "members", [_member("twin", name="Rob Jetten", slug="rob-jetten")]
    )
    report = Report()
    _check_member_slugs(store, report)
    assert report.problems and "rob-jetten (2)" in report.problems[0]
