"""The queries of ``semantic tk-government`` on a real PostgreSQL: the people who held a
post, the cabinet periods, who made a commitment, and who signed a dossier's earliest
document first."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lawgraph.db import CountingStore, GraphStore
from lawgraph.db.queries.government import (
    ROLE_FIRST_SIGNATORY,
    cabinet_periods,
    commitment_makers,
    dossier_first_signatures,
    government_people,
)


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **meta: Any) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "meta": meta,
    }


def _signed(key: str, member: str, document: str, capacity: str, **meta: Any) -> dict:
    return _edge(
        key,
        f"members/{member}",
        f"documents/{document}",
        "AUTHORED",
        role=meta.pop("role", ROLE_FIRST_SIGNATORY),
        capacity=capacity,
        **meta,
    )


def test_the_people_with_a_post_by_their_government_name(store: GraphStore) -> None:
    post = {"cabinet_key": "rutte", "ministry": "fin"}
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _node(
                "m1",
                name="Eelco Heinen",
                government_name="E. Heinen",
                government_functions=[post],
            ),
            # no government name (or an empty one): the name
            _node(
                "m2", name="Rob Jetten", government_name="", government_functions=[post]
            ),
            _node("m3", name="Piet", government_functions=[post]),
            # posts that are not there, or empty
            _node("m4", name="Kamerlid"),
            _node("m5", name="Leeg", government_functions=[]),
            _node("m6", name="Object", government_functions={}),
            # keys in byte order: upper case before lower case
            _node("Zz", government_name="Z. Z.", government_functions=[post]),
            _node("aa", government_name="A. A.", government_functions=[post]),
        ],
    )
    people = list(government_people(store))
    assert [p["id"] for p in people] == ["Zz", "aa", "m1", "m2", "m3"]
    assert [p["name"] for p in people] == [
        "Z. Z.",
        "A. A.",
        "E. Heinen",
        "Rob Jetten",
        "Piet",
    ]
    assert json.dumps(people[2]) == json.dumps(
        {"id": "m1", "name": "E. Heinen", "posts": [post]}
    )


def test_the_cabinet_periods(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node("schoof", from_date="2024-07-02", to_date=None),
            _node("Rutte", from_date="2010-10-14", to_date="2012-11-05", name="x"),
            _node("jetten", from_date="2026-02-23"),
        ],
    )
    periods = list(cabinet_periods(store))
    assert periods == [
        {"key": "Rutte", "from_date": "2010-10-14", "to_date": "2012-11-05"},
        {"key": "jetten", "from_date": "2026-02-23", "to_date": None},
        {"key": "schoof", "from_date": "2024-07-02", "to_date": None},
    ]
    assert all(list(p) == ["key", "from_date", "to_date"] for p in periods)
    # through the store that counts what a pipeline writes
    assert list(cabinet_periods(CountingStore(store))) == periods


def test_who_made_a_commitment_with_what_is_stored_of_it(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "commitments",
        [
            _node(
                "k1",
                text="De minister stuurt een brief.",
                minister_name="Heinen, E.",
                minister_role="Minister van Financiën",
                ministry_name="Financiën",
                made_on="2026-04-01",
                post="minister",
                member_key="heinen",
                cabinet="schoof",
                ministry=None,
                status="Openstaand",
            ),
            _node("k0", text="Zonder maker"),
        ],
    )
    rows = list(commitment_makers(store))
    assert [r["key"] for r in rows] == ["k0", "k1"]
    assert rows[0] == {
        "key": "k0",
        "name": None,
        "role": None,
        "ministry_name": None,
        "text": "Zonder maker",
        "date": None,
        "props": {},
    }
    made = rows[1]
    assert list(made) == [
        "key",
        "name",
        "role",
        "ministry_name",
        "text",
        "date",
        "props",
    ]
    assert (made["name"], made["role"], made["date"]) == (
        "Heinen, E.",
        "Minister van Financiën",
        "2026-04-01",
    )
    # KEEP: the stored keys of the four, null ones too, in byte order
    assert json.dumps(made["props"]) == json.dumps(
        {
            "cabinet": "schoof",
            "member_key": "heinen",
            "ministry": None,
            "post": "minister",
        }
    )


@pytest.fixture()
def signatures(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [
            _node("d1", ministry="fin", initiative=False, cabinet="rutte", kind="x"),
            _node("d2"),
            _node("d3"),
            _node("D0", cabinet="schoof"),
        ],
    )
    store.bulk_insert_or_update_nodes("cases", [_node("c1")])
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("early", date="2020-01-01"),
            _node("late", date="2021-01-01"),
            _node("undated"),
            _node("same_a", date="2022-01-01"),
            _node("same_b", date="2022-01-01"),
            _node("pair", date="2023-01-01"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            # d1: a document directly, one through a case, one without a date
            _edge("p1", "documents/late", "dossiers/d1", "PART_OF"),
            _edge("p2", "documents/early", "cases/c1", "PART_OF"),
            _edge("p3", "cases/c1", "dossiers/d1", "PART_OF"),
            _edge("p4", "documents/undated", "dossiers/d1", "PART_OF"),
            # d2: two documents of a day; d3: one document signed first twice
            _edge("p5", "documents/same_b", "dossiers/d2", "PART_OF"),
            _edge("p6", "documents/same_a", "dossiers/d2", "PART_OF"),
            _edge("p7", "documents/pair", "dossiers/d3", "PART_OF"),
            _signed("a1", "kamerlid", "late", "kamerlid", function="Tweede Kamerlid"),
            _signed("a2", "heinen", "early", "bewindspersoon", function="minister"),
            _signed("a3", "jetten", "undated", "bewindspersoon"),
            # not a first signatory, and a capacity that does not count
            _signed("a4", "x", "early", "bewindspersoon", role="Mede ondertekenaar"),
            _signed("a0", "y", "early", "ambtenaar"),
            _signed("a5", "heinen", "same_b", "bewindspersoon"),
            _signed("a6", "jetten", "same_a", "bewindspersoon"),
            _signed("b9", "heinen", "pair", "bewindspersoon"),
            _signed("b1", "jetten", "pair", "kamerlid"),
        ]
    )
    return store


def test_a_dossier_is_brought_in_by_the_first_signature_of_its_earliest_document(
    signatures: GraphStore,
) -> None:
    rows = {r["key"]: r for r in dossier_first_signatures(signatures)}
    assert [r["key"] for r in dossier_first_signatures(signatures)] == [
        "D0",
        "d1",
        "d2",
        "d3",
    ]
    d1 = rows["d1"]
    assert list(d1) == ["key", "first", "props"]
    # through the case; the undated document does not count
    assert json.dumps(d1["first"]) == json.dumps(
        {
            "date": "2020-01-01",
            "member": "heinen",
            "capacity": "bewindspersoon",
            "function": "minister",
            "paper": "documents/early",
        }
    )
    # KEEP: the three in byte order, the others left out
    assert json.dumps(d1["props"]) == json.dumps(
        {"cabinet": "rutte", "initiative": False, "ministry": "fin"}
    )
    # two documents of a day: the document id settles it; one document: the edge key
    assert rows["d2"]["first"]["member"] == "jetten"
    assert rows["d3"]["first"] == {
        "date": "2023-01-01",
        "member": "jetten",
        "capacity": "kamerlid",
        "function": None,
        "paper": "documents/pair",
    }
    assert rows["D0"] == {"key": "D0", "first": None, "props": {"cabinet": "schoof"}}


def test_nothing_signed_nothing_found(store: GraphStore) -> None:
    assert list(dossier_first_signatures(store)) == []
    assert list(government_people(store)) == []
    store.bulk_insert_or_update_nodes("dossiers", [_node("d1")])
    assert list(dossier_first_signatures(store)) == [
        {"key": "d1", "first": None, "props": {}}
    ]
