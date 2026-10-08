"""The reads and the removal of the Tweede and Eerste Kamer and Rijksoverheid normalize
steps on a real PostgreSQL: which rows, in which order, with which values (nulls, missing
props and props of another type as ArangoDB saw them), and what a removal leaves."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from lawgraph.config.constants import (
    CHAMBER_TK,
    RELATION_AUTHORED,
    RELATION_MEMBER_OF,
    RELATION_VOTED,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT
from lawgraph.db import GraphStore
from lawgraph.db.queries.normalize import tk as queries

GOV = CAPACITY_GOVERNMENT


def _node(key: str, labels: list[str] | None = None, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": labels or [], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **rest: Any) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "tk",
        **rest,
    }


def _seed(store: GraphStore, collection: str, *docs: dict[str, Any]) -> None:
    store.bulk_insert_or_update_nodes(collection, list(docs))


def _signed(key: str, member: str, document: str, **meta: Any) -> dict[str, Any]:
    return _edge(
        key,
        f"members/{member}",
        f"documents/{document}",
        RELATION_AUTHORED,
        meta={"capacity": GOV, **meta},
    )


# ── cases, nodes by TK Id, factions, dossiers ────────────────────────────────


def test_case_dossier_numbers_are_the_cases_with_numbers_by_key(
    store: GraphStore,
) -> None:
    _seed(
        store,
        "cases",
        _node("case2", dossier_numbers=["36000", "36001"]),
        _node("Case1", dossier_numbers="36002"),
        _node("case3", dossier_numbers=None),
        _node("case4"),
        _node("case5", dossier_numbers=[]),
    )
    rows = list(queries.case_dossier_numbers(store))
    assert rows == [
        {"id": "cases/Case1", "dossier_numbers": "36002"},
        {"id": "cases/case2", "dossier_numbers": ["36000", "36001"]},
        {"id": "cases/case5", "dossier_numbers": []},
    ]
    assert [list(row) for row in rows] == [["id", "dossier_numbers"]] * 3


def test_case_dossier_numbers_of_some_cases_and_of_those_naming_dossiers(
    store: GraphStore,
) -> None:
    """What a poll links: the cases of its window, by id, and the cases that name a
    dossier it wrote, as a list or as one string."""
    _seed(
        store,
        "cases",
        _node("case2", dossier_numbers=["36000", "36001"]),
        _node("Case1", dossier_numbers="36002"),
        _node("case3", dossier_numbers=None),
        _node("case4", dossier_numbers=["36003"]),
    )
    assert [
        row["id"]
        for row in queries.case_dossier_numbers_of(
            store, ["cases/case2", "cases/case3", "cases/none"]
        )
    ] == ["cases/case2"]
    assert [
        row["id"]
        for row in queries.case_dossier_numbers_naming(store, ["36001", "36002"])
    ] == ["cases/Case1", "cases/case2"]
    assert list(queries.case_dossier_numbers_naming(store, ["99999"])) == []


def test_dossiers_by_key_in_one_read(store: GraphStore) -> None:
    _seed(store, "dossiers", _node("36000", title="A"), _node("37020_xv", title="B"))
    rows = list(queries.dossiers_by_key(store, ["37020_xv", "99999", "36000"]))
    assert [row["key"] for row in rows] == ["36000", "37020_xv"]
    assert rows[0]["id"] == "dossiers/36000" and rows[0]["props"]["title"] == "A"


def test_case_dossier_numbers_of_no_cases(store: GraphStore) -> None:
    assert list(queries.case_dossier_numbers(store)) == []


def test_nodes_by_external_id_keep_the_props_named_in_byte_order(
    store: GraphStore,
) -> None:
    _seed(
        store,
        "documents",
        _node("d2", external_id="D1", text="lang", b=1, a=None, date="2024-01-01"),
        _node("d1", external_id=5),
        _node("d3", external_id=None, b=1),
        _node("d4", b=1),
        _node("D0", external_id="D1", B=2),
    )
    rows = list(queries.nodes_by_external_id(store, "documents", ["b", "a", "B", "zz"]))
    assert rows == [
        {"key": "D0", "id": "D1", "props": {"B": 2}},
        {"key": "d1", "id": 5, "props": {}},
        {"key": "d2", "id": "D1", "props": {"a": None, "b": 1}},
    ]
    assert list(rows[2]["props"]) == ["a", "b"]
    assert [list(row) for row in rows] == [["key", "id", "props"]] * 3
    assert [
        r["props"] for r in queries.nodes_by_external_id(store, "documents", [])
    ] == [
        {},
        {},
        {},
    ]
    assert list(queries.nodes_by_external_id(store, "cases", ["b"])) == []


def test_faction_aliases_are_every_alias_once(store: GraphStore) -> None:
    _seed(
        store,
        "factions",
        _node("vvd", aliases=["Volkspartij", "VVD"]),
        _node("ek_vvd", aliases=["VVD", "vvd", None, 3, ["x"]]),
        _node("cda", aliases=[]),
        _node("x", aliases=None),
        _node("y", aliases=""),
        _node("z"),
    )
    # sorted as ArangoDB sorts values; a set to its reader
    assert list(queries.faction_aliases(store)) == [
        None,
        3,
        "Volkspartij",
        "VVD",
        "vvd",
        ["x"],
    ]


def test_faction_aliases_of_another_type_fail_as_in_arangodb(
    store: GraphStore,
) -> None:
    # ``FOR alias IN "Losse naam"`` raised; so does this
    _seed(store, "factions", _node("w", aliases="Losse naam"))
    with pytest.raises(psycopg.Error):
        list(queries.faction_aliases(store))


def test_dossier_case_kinds_of_the_keys_asked(store: GraphStore) -> None:
    _seed(
        store,
        "dossiers",
        _node("36000", case_kinds=["Wetgeving"]),
        _node("36000_vii", case_kinds="x"),
        _node("36001"),
        _node("D9", case_kinds={"a": 1}),
    )
    rows = list(
        queries.dossier_case_kinds(store, ["36001", "36000", "nope", "36000", "D9"])
    )
    assert rows == [
        {"key": "36000", "case_kinds": ["Wetgeving"]},
        {"key": "36001", "case_kinds": None},
        {"key": "D9", "case_kinds": {"a": 1}},
    ]
    assert list(queries.dossier_case_kinds(store, [])) == []


def test_dossiers_of_numbers_compare_strings_only(store: GraphStore) -> None:
    _seed(
        store,
        "dossiers",
        _node("36000", number="36000", same_number_count=0),
        _node("36000_vii", number="36000", same_number_count=None),
        _node("36000_ii", number="36000"),
        _node("d99", number=99, same_number_count=1),
        _node("D98", number="99", same_number_count=1.5),
    )
    rows = list(queries.dossiers_of_numbers(store, ["36000", "99", "99"]))
    assert rows == [
        {"key": "36000", "number": "36000", "same_number_count": 0},
        {"key": "36000_ii", "number": "36000", "same_number_count": None},
        {"key": "36000_vii", "number": "36000", "same_number_count": None},
        {"key": "D98", "number": "99", "same_number_count": 1.5},
    ]
    assert json.dumps(rows[0]["same_number_count"]) == "0"
    assert list(queries.dossiers_of_numbers(store, [])) == []


# ── members ──────────────────────────────────────────────────────────────────


def test_member_identities_of_tk_persons_with_a_surname(store: GraphStore) -> None:
    _seed(
        store,
        "members",
        _node(
            "m1",
            [CHAMBER_TK],
            family_name="Bakker",
            full_name="Anna Bakker",
            name="A. Bakker",
            initials="A.",
            birth_date="1970-01-01",
            faction_memberships=[
                {"faction_key": "vvd"},
                {"faction_key": "cda"},
                {"faction_key": "vvd"},
                {"x": 1},
            ],
        ),
        _node("m2", [CHAMBER_TK], family_name="Vries", full_name="", name="C. Vries"),
        _node(
            "Zz",
            [CHAMBER_TK],
            family_name=5,
            full_name=0,
            name=None,
            faction_memberships=[
                {"faction_key": 3},
                {"faction_key": "abc"},
                {"faction_key": "Abc"},
                "s",
                {"faction_key": True},
            ],
        ),
        _node("w", [CHAMBER_TK], family_name="W", faction_memberships="x"),
        _node("m3", [CHAMBER_TK], family_name=None, name="Min"),
        _node("m4", [CHAMBER_TK], name="Geen achternaam"),
        _node("m5", ["Rijksoverheid"], family_name="Z"),
    )
    rows = list(queries.member_identities(store))
    assert rows == [
        {
            "key": "Zz",
            "family_name": 5,
            "name": None,
            "initials": None,
            "birth_date": None,
            "factions": [None, True, 3, "Abc", "abc"],
        },
        {
            "key": "m1",
            "family_name": "Bakker",
            "name": "Anna Bakker",
            "initials": "A.",
            "birth_date": "1970-01-01",
            "factions": [None, "cda", "vvd"],
        },
        {
            "key": "m2",
            "family_name": "Vries",
            "name": "C. Vries",
            "initials": None,
            "birth_date": None,
            "factions": [],
        },
        {
            "key": "w",
            "family_name": "W",
            "name": None,
            "initials": None,
            "birth_date": None,
            "factions": [],
        },
    ]
    assert list(rows[0]) == [
        "key",
        "family_name",
        "name",
        "initials",
        "birth_date",
        "factions",
    ]


def test_labelled_and_government_members_by_key(store: GraphStore) -> None:
    _seed(
        store,
        "members",
        _node("m1", [CHAMBER_TK], government_functions=[{"cabinet_key": "c"}]),
        _node("Zz", [CHAMBER_TK, "Rijksoverheid"], government_functions=[]),
        _node("aa", ["Rijksoverheid"], government_functions={}),
        _node("m2", [], government_functions=None),
        _node("m3", ["TK2"]),
    )
    assert list(queries.labelled_members(store, CHAMBER_TK)) == ["Zz", "m1"]
    assert list(queries.labelled_members(store, "Rijksoverheid")) == ["Zz", "aa"]
    assert list(queries.labelled_members(store, "nope")) == []
    assert list(queries.government_members(store)) == ["Zz", "aa", "m1"]


def test_members_born_on_compare_strings_only(store: GraphStore) -> None:
    _seed(
        store,
        "members",
        _node("m2", family_name="Vries", birth_date="1970-01-01", text="x"),
        _node("m1", birth_date="1970-01-01"),
        _node("m3", family_name="Num", birth_date=19700101),
        _node("Zz", family_name=5, birth_date="1980-02-02"),
    )
    rows = list(
        queries.members_born_on(store, ["1980-02-02", "1970-01-01", "1970-01-01"])
    )
    assert rows == [
        {"key": "Zz", "family_name": 5, "birth_date": "1980-02-02"},
        {"key": "m1", "family_name": None, "birth_date": "1970-01-01"},
        {"key": "m2", "family_name": "Vries", "birth_date": "1970-01-01"},
    ]
    assert list(rows[0]) == ["key", "family_name", "birth_date"]
    assert list(queries.members_born_on(store, ["19700101"])) == []
    assert list(queries.members_born_on(store, [])) == []


def test_remove_members_removes_them_with_their_edges(store: GraphStore) -> None:
    _seed(store, "members", _node("m1"), _node("m2"), _node("m3"))
    _seed(store, "factions", _node("vvd"))
    store.bulk_insert_or_update_edges(
        [
            _edge("e1", "members/m1", "factions/vvd", RELATION_MEMBER_OF),
            _edge("e2", "members/m1", "members/m2", "RELATED_TO"),
            _edge("e3", "factions/vvd", "members/m2", "RELATED_TO"),
            _edge("e4", "members/m3", "factions/vvd", RELATION_MEMBER_OF),
        ]
    )
    # an edge between two members that go goes once; a key without a member is passed
    assert queries.remove_members(store, ["m1", "m2", "nope"]) == 2
    assert sorted(store.query("SELECT key FROM members")) == ["m3"]
    assert sorted(store.query("SELECT key FROM edges")) == ["e4"]
    assert queries.remove_members(store, []) == 0


# ── government signatures ────────────────────────────────────────────────────


def _signatures_graph(store: GraphStore) -> None:
    minister = {"person_id": "p3", "name": "J. Minister"}
    _seed(
        store,
        "members",
        _node("m3", [CHAMBER_TK], external_id="p3", name="Min"),
        _node("m1", [CHAMBER_TK], family_name="Bakker", external_id="p1"),
        _node("m4", [CHAMBER_TK], family_name=None),
        _node("m5", ["Rijksoverheid"], external_id="p3"),
        _node("Zz", [CHAMBER_TK], family_name="Zet"),
    )
    _seed(
        store,
        "documents",
        _node(
            "d1",
            date="2023-01-15",
            actors=[minister, minister, {"person_id": "p1", "name": "A"}],
        ),
        _node(
            "d2",
            date="2023-03-02",
            actors=[
                minister,
                {"person_id": "p3", "name": "Jan Minister"},
                {"name": "anon"},
                "junk",
                {"person_id": "p3"},
                {"person_id": "p3", "name": None},
            ],
        ),
        _node("d3", date=20230401, actors=[minister]),
        _node("d4", date=None, actors=[minister]),
        _node("d5", actors=[minister]),
        _node("d6", date=True, actors=[{"person_id": "p3", "name": 5}]),
        _node("d7", date="2023-03-30", actors=None),
        _node("d8", date="2023-01-01", actors=[]),
        _node("d9", date=["2023"], actors=[minister]),
        _node("d10", date="2023-12-01", actors=[{"name": "Nobody"}]),
        _node("d11", date="2023-03-01", actors=[minister]),
        _node("d12", date=False, actors=[minister]),
        _node(
            "d13",
            date="2023-01-15",
            actors=[{"person_id": "p3", "name": "j. minister"}],
        ),
    )
    x = "minister van X"
    store.bulk_insert_or_update_edges(
        [
            _signed("a01", "m3", "d1", function=x),
            _signed("a02", "m3", "d2", function=x),
            _signed("a03", "m3", "d3", function=x),
            _signed("a04", "m3", "d6"),
            _signed("a05", "m3", "d9", function="staatssecretaris"),
            _signed("a06", "m3", "d4", function=x),
            _signed("a07", "m3", "d5", function=x),
            _signed("a08", "m3", "d7", function=x),
            _edge(
                "a09",
                "members/m3",
                "documents/d1",
                RELATION_AUTHORED,
                meta={"capacity": "lid", "function": x},
            ),
            _signed("a10", "m1", "d1", function="minister van Y"),
            _signed("a11", "m1", "d3", function="minister van Y"),
            _signed("a12", "m1", "d6", function="minister van Y"),
            _signed("a13", "m4", "d10", function="f"),
            _signed("a14", "m5", "d1", function="f"),
            _signed("a15", "gone", "d1", function="f"),
            _signed("a16", "m3", "gone", function="f"),
            _signed("a17", "Zz", "d8", function=7),
            _edge(
                "a18",
                "members/m3",
                "documents/d2",
                RELATION_AUTHORED,
                meta={"capacity": [GOV], "function": "g"},
            ),
            _edge("a19", "members/m3", "documents/d2", RELATION_AUTHORED),
            _signed("a20", "m3", "d11", function=x),
            _signed("a21", "m3", "d12", function=x),
            _signed("a22", "m3", "d13", function=x),
            _signed("a23", "m3", "d11", function=None),
        ]
    )


def test_government_signatures_per_person_name_and_function(
    store: GraphStore,
) -> None:
    _signatures_graph(store)
    rows = list(queries.government_signatures(store))
    x = "minister van X"
    # sorted by person, name and function as ArangoDB sorts values; the first and last
    # date as MIN and MAX of values of any type; an actor without person_id is the person
    # without external_id
    assert rows == [
        {"key": "m3", "name": 5, "function": None, "first": True, "last": True},
        {
            "key": "m3",
            "name": "J. Minister",
            "function": None,
            "first": "2023-03-01",
            "last": "2023-03-01",
        },
        {
            "key": "m3",
            "name": "J. Minister",
            "function": x,
            "first": False,
            "last": "2023-03-02",
        },
        {
            "key": "m3",
            "name": "J. Minister",
            "function": "staatssecretaris",
            "first": ["2023"],
            "last": ["2023"],
        },
        {
            "key": "m3",
            "name": "j. minister",
            "function": x,
            "first": "2023-01-15",
            "last": "2023-01-15",
        },
        {
            "key": "m3",
            "name": "Jan Minister",
            "function": x,
            "first": "2023-03-02",
            "last": "2023-03-02",
        },
        {
            "key": "m4",
            "name": "Nobody",
            "function": "f",
            "first": "2023-12-01",
            "last": "2023-12-01",
        },
    ]
    assert list(rows[0]) == ["key", "name", "function", "first", "last"]


def test_government_signatures_by_month(store: GraphStore) -> None:
    _signatures_graph(store)
    rows = list(queries.government_signatures_by_month(store))
    x = "minister van X"
    y = "minister van Y"
    # by person in the order of the collation (Zz after m4), function and month; the month
    # of a date of another type is the start of its text ("2023040", "true")
    assert rows == [
        {"key": "m1", "function": y, "first": "2023-01-15", "last": "2023-01-15"},
        {"key": "m1", "function": y, "first": 20230401, "last": 20230401},
        {"key": "m1", "function": y, "first": True, "last": True},
        {"key": "m3", "function": None, "first": "2023-03-01", "last": "2023-03-01"},
        {"key": "m3", "function": None, "first": True, "last": True},
        {"key": "m3", "function": x, "first": "2023-01-15", "last": "2023-01-15"},
        {"key": "m3", "function": x, "first": "2023-03-01", "last": "2023-03-30"},
        {"key": "m3", "function": x, "first": 20230401, "last": 20230401},
        {"key": "m3", "function": x, "first": False, "last": False},
        {
            "key": "m3",
            "function": "staatssecretaris",
            "first": ["2023"],
            "last": ["2023"],
        },
        {"key": "m4", "function": "f", "first": "2023-12-01", "last": "2023-12-01"},
        {"key": "Zz", "function": 7, "first": "2023-01-01", "last": "2023-01-01"},
    ]
    assert list(rows[0]) == ["key", "function", "first", "last"]
    assert json.dumps(rows[1]["first"]) == "20230401"


def test_government_signatures_of_no_edges(store: GraphStore) -> None:
    assert list(queries.government_signatures(store)) == []
    assert list(queries.government_signatures_by_month(store)) == []


# ── votes ────────────────────────────────────────────────────────────────────


def test_decisions_of_vote_records(store: GraphStore) -> None:
    _seed(
        store,
        "decisions",
        _node("b1", decision_id="B1"),
        _node("b2"),
        _node("b3", decision_id="B3"),
        _node("b4", decision_id=5),
        _node("B0", decision_id=None),
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(
                "v1",
                "factions/vvd",
                "decisions/b1",
                RELATION_VOTED,
                meta={"record_ids": ["r1", "r2"]},
            ),
            _edge(
                "v2",
                "members/m1",
                "decisions/b1",
                RELATION_VOTED,
                meta={"record_ids": ["r1"]},
            ),
            _edge(
                "v3",
                "factions/cda",
                "decisions/b2",
                RELATION_VOTED,
                meta={"record_ids": ["r3"]},
            ),
            _edge(
                "v4",
                "factions/cda",
                "decisions/gone",
                RELATION_VOTED,
                meta={"record_ids": ["r1"]},
            ),
            _edge(
                "v5",
                "factions/cda",
                "decisions/b3",
                RELATION_VOTED,
                meta={"record_ids": "r1"},
            ),
            _edge(
                "v6",
                "factions/cda",
                "decisions/b4",
                RELATION_VOTED,
                meta={"record_ids": [1, "r4"]},
            ),
            _edge(
                "v7",
                "factions/cda",
                "decisions/B0",
                RELATION_VOTED,
                meta={"record_ids": ["r5"]},
            ),
            _edge(
                "v8",
                "members/m1",
                "decisions/b3",
                RELATION_AUTHORED,
                meta={"record_ids": ["r1"]},
            ),
        ]
    )

    def asked(*ids: str) -> list[dict[str, Any]]:
        return list(queries.decisions_of_vote_records(store, list(ids)))

    assert asked("r1", "r3") == [
        {"key": "b1", "decision_id": "B1"},
        {"key": "b2", "decision_id": None},
    ]
    assert asked("r1", "r1") == [{"key": "b1", "decision_id": "B1"}]
    assert asked("r4") == [{"key": "b4", "decision_id": 5}]
    assert asked("r5", "r2") == [
        {"key": "B0", "decision_id": None},
        {"key": "b1", "decision_id": "B1"},
    ]
    assert asked() == []
    assert asked("nope") == []


# ── factions and the Eerste Kamer ────────────────────────────────────────────


def test_faction_names_of_every_faction_but_the_eerste_kamer(
    store: GraphStore,
) -> None:
    _seed(
        store,
        "factions",
        _node("vvd", chamber="TK", name="VVD naam", abbreviation="VVD", aliases=["V"]),
        _node("ek_vvd", chamber="EK", name="VVD"),
        _node("cda", name="CDA", aliases=[]),
        _node("f5", chamber=5, name=7),
        _node("Ek", chamber="ek"),
    )
    rows = list(queries.faction_names(store))
    assert rows == [
        {"key": "Ek", "name": None, "abbreviation": None, "aliases": None},
        {"key": "cda", "name": "CDA", "abbreviation": None, "aliases": []},
        {"key": "f5", "name": 7, "abbreviation": None, "aliases": None},
        {"key": "vvd", "name": "VVD naam", "abbreviation": "VVD", "aliases": ["V"]},
    ]
    assert list(rows[0]) == ["key", "name", "abbreviation", "aliases"]


def test_ek_composition(store: GraphStore) -> None:
    _seed(
        store,
        "factions",
        _node("ek_vvd", chamber="EK", name="VVD", data_since="2020"),
        _node("ek_x", chamber="EK"),
        _node("vvd", chamber="TK"),
        _node("ek_5", chamber=5),
    )
    _seed(
        store,
        "committees",
        _node("c1", chamber="EK", name="Justitie"),
        _node("c2", chamber="TK"),
        _node("C0", chamber="EK"),
    )
    _seed(
        store,
        "members",
        _node("m1", ek={"path": "/a"}),
        _node("aa", ek={}),
        _node("m2", ek=None),
        _node("m3"),
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(
                "e1",
                "members/m1",
                "factions/ek_vvd",
                RELATION_MEMBER_OF,
                meta={"from": "2020"},
            ),
            _edge("e0", "members/m2", "factions/ek_vvd", RELATION_MEMBER_OF),
            _edge(
                "e2",
                "members/m3",
                "committees/c1",
                RELATION_MEMBER_OF,
                meta={"role": "lid"},
            ),
            _edge("e3", "members/m1", "committees/c2", RELATION_MEMBER_OF, meta={}),
            _edge("e4", "members/m1", "factions/ek_x", "PART_OF"),
            _edge("e5", "members/gone", "committees/C0", RELATION_MEMBER_OF, meta=None),
        ]
    )
    state = queries.ek_composition(store)
    assert list(state) == ["factions", "committees", "members", "edges"]
    assert [(f["key"], f["props"]["chamber"]) for f in state["factions"]] == [
        ("ek_vvd", "EK"),
        ("ek_x", "EK"),
    ]
    assert [c["key"] for c in state["committees"]] == ["C0", "c1"]
    assert all(list(row) == ["key", "props"] for row in state["committees"])
    assert state["members"] == [
        {"key": "aa", "ek": {}},
        {"key": "m1", "ek": {"path": "/a"}},
    ]
    # per target, the factions before the committees; by edge key within one
    assert state["edges"] == [
        {"from": "members/m2", "to": "factions/ek_vvd", "meta": None},
        {"from": "members/m1", "to": "factions/ek_vvd", "meta": {"from": "2020"}},
        {"from": "members/gone", "to": "committees/C0", "meta": None},
        {"from": "members/m3", "to": "committees/c1", "meta": {"role": "lid"}},
    ]
    assert list(state["edges"][0]) == ["from", "to", "meta"]


def test_ek_composition_of_an_empty_graph(store: GraphStore) -> None:
    assert queries.ek_composition(store) == {
        "factions": [],
        "committees": [],
        "members": [],
        "edges": [],
    }
