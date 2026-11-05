"""An office on a real PostgreSQL: its holders over the renames, its gaps, and what the lists
of commitments and dossiers keep of it."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries.commitments import get_commitments
from lawgraph.db.queries.dossier_filters import DossierFilters
from lawgraph.db.queries.dossiers import get_dossiers
from lawgraph.db.queries.seats import get_seat
from tests.pg.cabinet_graph import node


def _post(seat: str, ministry: str | None, begin: str, end: str | None) -> dict:
    kind = "staatssecretaris" if "staatssecretaris" in seat else "minister"
    return {
        "seat": seat,
        "ministry": ministry,
        "post": kind,
        "function": f"{kind} van {ministry}",
        "cabinet_key": "c1",
        "cabinet": "kabinet-Een",
        "from_date": begin,
        "to_date": end,
        "acting": False,
    }


def _commitment(
    key: str, member: str | None, day: str, ministry: str, role: str
) -> dict:
    return node(
        key, member_key=member, made_on=day, ministry=ministry, minister_role=role
    )


def _dossier(key: str, member: str, day: str, function: str, ministry: str) -> dict:
    first = {
        "date": day,
        "member": member,
        "capacity": "bewindspersoon",
        "function": function,
    }
    return node(
        key,
        label=key,
        number=key,
        kind="Wetgeving",
        ministry=ministry,
        first_signed=first,
    )


MINISTER = "Minister van Infrastructuur en Waterstaat"


@pytest.fixture()
def offices(store: GraphStore) -> GraphStore:
    ienm = _post("ienm/minister", "ienm", "2012-01-01", "2017-10-26")
    nodes: dict[str, list[dict[str, Any]]] = {
        "members": [
            node("schultz", name="Schultz", government_functions=[ienm]),
            node(
                "harbers",
                name="Harbers",
                slug="mark-harbers",
                government_functions=[
                    _post("ienw/minister", "ienw", "2022-01-10", None)
                ],
            ),
            node(
                "double",
                name="Twee Petten",
                government_functions=[
                    _post("ienw/staatssecretaris", "ienw", "2022-01-10", None),
                    _post("fin/staatssecretaris#2", "fin", "2022-01-10", None),
                ],
            ),
            node("kamerlid", name="Geen Post"),
        ],
        "commitments": [
            _commitment("old", "schultz", "2015-03-01", "ienm", MINISTER),
            _commitment("new", "harbers", "2023-03-01", "ienw", MINISTER),
            _commitment("filed", "harbers", "2023-03-02", "bzk", MINISTER),
            _commitment("nobody", None, "2023-03-03", "ienw", MINISTER),
            _commitment("vacant", None, "2019-01-01", "ienw", MINISTER),
            _commitment("no-office", "kamerlid", "2023-03-04", "ienw", MINISTER),
            _commitment(
                "other-kind", None, "2023-03-05", "ienw", "Staatssecretaris van IenW"
            ),
            _commitment("two", "double", "2023-04-01", "bzk", "Staatssecretaris"),
            _commitment(
                "one-of-two", "double", "2023-04-02", "fin", "Staatssecretaris"
            ),
        ],
        "dossiers": [
            _dossier("37001", "harbers", "2023-05-01", MINISTER, "ienw"),
            _dossier("37002", "schultz", "2015-05-01", MINISTER, "ienm"),
            _dossier("37003", "kamerlid", "2023-05-02", MINISTER, "ienw"),
            node(
                "37004",
                label="37004",
                number="37004",
                kind="Wetgeving",
                ministry="ienw",
            ),
            node(
                "37005",
                label="37005",
                number="37005",
                kind="Wetgeving",
                first_signed={
                    "date": "2023-05-03",
                    "member": "harbers",
                    "capacity": "kamerlid",
                    "function": None,
                },
            ),
        ],
    }
    for collection, docs in nodes.items():
        store.bulk_insert_or_update_nodes(collection, docs)
    return store


def _keys(raw: dict[str, Any]) -> list[str]:
    return sorted(item.get("commitment", item)["key"] for item in raw["items"])


def test_the_holders_of_an_office_over_its_renames(offices: GraphStore) -> None:
    seat = get_seat(offices, "ienm/minister")
    assert seat is not None
    assert seat == get_seat(offices, "ienw/minister")
    assert seat["seat"] == "ienw/minister"
    assert seat["names"] == ["ienm/minister", "ienw/minister"]
    assert [p["member"]["key"] for p in seat["holders"]] == ["schultz", "harbers"]
    assert seat["holders"][1]["member"]["slug"] == "mark-harbers"
    # nobody held it between the two: a gap, not filled in
    assert seat["gaps"] == [{"from_date": "2017-10-26", "to_date": "2022-01-10"}]
    # a merger is named, only of a seat someone held: nobody here held venw/minister
    assert seat["merged_from"] == []


def test_what_is_attributed_and_what_fits_nobody(offices: GraphStore) -> None:
    seat = get_seat(offices, "ienw/minister")
    assert seat is not None
    assert sorted(i.partition("/")[2] for i in seat["commitments"].ids) == [
        "filed",  # filed under another ministry: the post held that day decides
        "new",
        "old",
    ]
    # no member, or one without a post, of its ministry and kind on a day it was held;
    # not ``vacant`` (nobody held it) nor ``other-kind``
    assert seat["commitments"].unattributed == 2
    assert sorted(i.partition("/")[2] for i in seat["dossiers"].ids) == [
        "37001",
        "37002",
    ]
    assert seat["dossiers"].unattributed == 1


def test_an_unknown_seat(offices: GraphStore) -> None:
    assert get_seat(offices, "fin/minister") is None
    assert get_commitments(offices, seat="fin/minister", facets=False)["total"] == 0


def test_the_lists_keep_what_is_attributed(offices: GraphStore) -> None:
    raw = get_commitments(offices, seat="ienm/minister")
    assert _keys(raw) == ["filed", "new", "old"]
    assert raw["total"] == 3
    # with the other filters, and the facets under them
    made = get_commitments(offices, seat="ienw/minister", made_from="2020-01-01")
    assert _keys(made) == ["filed", "new"]
    assert {f["value"]: f["count"] for f in made["facets"]["ministry"]} == {
        "bzk": 1,
        "ienw": 1,
    }
    raw = get_dossiers(offices, DossierFilters(seat="ienw/minister"))
    assert _keys(raw) == ["37001", "37002"]
    assert raw["total"] == 2


def test_two_seats_that_day_the_ministry_decides(offices: GraphStore) -> None:
    lane = get_commitments(offices, seat="fin/staatssecretaris", facets=False)
    assert _keys(lane) == ["one-of-two"]
    other = get_commitments(offices, seat="ienw/staatssecretaris", facets=False)
    assert _keys(other) == []
