"""The cabinet and commitment queries on a real PostgreSQL: the cabinets with their counts,
a cabinet with its bewindspersonen, the commitments with their facets, and the posts that
``verify cabinets`` reads."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries.cabinets import (
    cabinets_with_posts,
    get_cabinet,
    get_cabinets,
    get_commitment,
    get_commitments,
)


def _node(key: str, labels: list[str] | None = None, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": labels or [], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **meta: Any) -> dict:
    edge = {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
    }
    return {**edge, "meta": meta} if meta else edge


@pytest.fixture()
def government(store: GraphStore) -> GraphStore:
    nodes = {
        "members": [
            _node("m1", name="Eelco Heinen"),
            # no name: the name it is known as, else the one Rijksoverheid gives
            _node("m2", name="", known_as="Bert"),
            _node(
                "m3",
                ["Rijksoverheid"],
                name=None,
                known_as="",
                government_name="C. de Vries",
            ),
            _node("m4", name="Dirk"),
        ],
        "cabinets": [
            _node("jetten", from_date="2026-02-23", to_date=None, prime_minister="m1"),
            _node(
                "schoof",
                from_date="2024-07-02",
                to_date="2026-02-23",
                prime_minister="m2",
            ),
            # the same first day as schoof: the key settles it
            _node("tie", from_date="2024-07-02", prime_minister="ghost"),
            _node("old"),
        ],
        "dossiers": [
            _node(
                "d1",
                label="36000",
                number="36000",
                title="T1",
                kind="Wetgeving",
                initiative=False,
                cabinet="jetten",
            ),
            _node(
                "d2",
                label="36000-VII",
                number="36000",
                title="T2",
                kind="Wetgeving",
                initiative=True,
                cabinet="jetten",
            ),
            _node("d3", label=None, kind="Overig", initiative=False, cabinet="jetten"),
            _node(
                "d4",
                label="36001",
                number="36001",
                kind="Wetgeving",
                initiative=False,
                cabinet="schoof",
            ),
        ],
        "cases": [_node("c1")],
        "documents": [
            _node("signed", date="2026-03-01"),
            _node("via_case", date="2026-03-02"),
            _node("before", date="2025-01-01"),
            _node("as_member", date="2026-03-03"),
            _node("undated"),
            _node("elsewhere", date="2026-03-04"),
        ],
        "activities": [
            _node("a1", date="2026-04-01", number="2026A01"),
            _node("a2", date="2026-04-02", number="2026A02"),
        ],
        "commitments": [
            _node(
                "k1",
                member_key="m1",
                cabinet="jetten",
                ministry="fin",
                status="Openstaand",
                made_on="2026-04-01",
                expected_resolution="2020-05-01",
                text="Een brief over Box 3",
            ),
            _node(
                "k2",
                member_key="m1",
                cabinet="jetten",
                ministry="fin",
                status="Openstaand",
                made_on="2026-04-02",
                expected_resolution="0001-01-01",
            ),
            _node(
                "k3",
                member_key="nobody",
                cabinet="schoof",
                status="Afgedaan",
                made_on="2026-04-01",
                expected_resolution="2025-01-01",
                text="Over de ÉCOLE",
            ),
            _node("k4", cabinet="jetten", status="Openstaand", made_on=None),
        ],
    }
    for collection, docs in nodes.items():
        store.bulk_insert_or_update_nodes(collection, docs)
    bewindspersoon = {"capacity": "bewindspersoon"}
    store.bulk_insert_or_update_edges(
        [
            _edge(
                "s0", "members/ghost", "cabinets/jetten", "SERVED_IN", posts=[{"p": 1}]
            ),
            _edge("s1", "members/m4", "cabinets/jetten", "SERVED_IN", posts=None),
            _edge(
                "s2",
                "members/m1",
                "cabinets/jetten",
                "SERVED_IN",
                posts=[{"post": "minister", "ministry": "fin"}],
            ),
            _edge(
                "s5",
                "members/m3",
                "cabinets/jetten",
                "SERVED_IN",
                posts=[{"z": 1, "a": 2}],
            ),
            _edge(
                "s3",
                "members/m2",
                "cabinets/schoof",
                "SERVED_IN",
                posts=[{"post": "minister"}],
            ),
            _edge(
                "s4",
                "members/m1",
                "cabinets/schoof",
                "SERVED_IN",
                posts=[{"member": "x", "seat": "y"}],
            ),
            # what m1 signed as a bewindspersoon: directly, through a case into two
            # dossiers, before jetten, as a Kamerlid, undated, and into a dossier gone
            _edge("a1", "members/m1", "documents/signed", "AUTHORED", **bewindspersoon),
            _edge(
                "a2", "members/m1", "documents/via_case", "AUTHORED", **bewindspersoon
            ),
            _edge("a3", "members/m1", "documents/before", "AUTHORED", **bewindspersoon),
            _edge(
                "a4",
                "members/m1",
                "documents/as_member",
                "AUTHORED",
                capacity="kamerlid",
            ),
            _edge(
                "a5", "members/m1", "documents/undated", "AUTHORED", **bewindspersoon
            ),
            _edge(
                "a6", "members/m1", "documents/elsewhere", "AUTHORED", **bewindspersoon
            ),
            _edge("p1", "documents/signed", "dossiers/d1", "PART_OF"),
            _edge("p2", "documents/via_case", "cases/c1", "PART_OF"),
            _edge("p3", "cases/c1", "dossiers/d1", "PART_OF"),
            _edge("p4", "cases/c1", "dossiers/d2", "PART_OF"),
            _edge("p5", "documents/before", "dossiers/d3", "PART_OF"),
            _edge("p6", "documents/as_member", "dossiers/d3", "PART_OF"),
            _edge("p7", "documents/undated", "dossiers/d3", "PART_OF"),
            _edge("p8", "documents/elsewhere", "dossiers/gone", "PART_OF"),
            _edge("b1", "commitments/k1", "dossiers/d1", "ABOUT"),
            _edge("b2", "commitments/k1", "dossiers/d3", "ABOUT"),
            _edge("b3", "commitments/k3", "dossiers/d2", "ABOUT"),
            _edge("b4", "commitments/k4", "dossiers/d4", "ABOUT"),
            _edge("i1", "commitments/k1", "activities/a2", "MADE_IN"),
            _edge("i2", "commitments/k1", "activities/a1", "MADE_IN"),
            _edge("i3", "commitments/k1", "activities/a0", "MADE_IN"),
        ]
    )
    return store


def test_the_cabinets_newest_first_with_their_counts(government: GraphStore) -> None:
    cabinets = get_cabinets(government)
    assert [c["cabinet"]["_key"] for c in cabinets] == [
        "jetten",
        "schoof",
        "tie",
        "old",
    ]
    jetten = cabinets[0]
    assert list(jetten) == [
        "cabinet",
        "prime_minister",
        "members",
        "bills",
        "commitments",
    ]
    assert jetten["cabinet"]["_id"] == "cabinets/jetten"
    assert json.dumps(jetten["prime_minister"]) == json.dumps(
        {"key": "m1", "name": "Eelco Heinen"}
    )
    # every SERVED_IN edge; the government bills; the commitments made under it
    assert (jetten["members"], jetten["bills"], jetten["commitments"]) == (4, 1, 3)
    schoof = cabinets[1]
    assert schoof["prime_minister"] == {"key": "m2", "name": "Bert"}
    assert (schoof["members"], schoof["bills"], schoof["commitments"]) == (2, 1, 1)
    # a prime minister nobody knows, and none
    assert [c["prime_minister"] for c in cabinets[2:]] == [None, None]
    assert [(c["members"], c["bills"], c["commitments"]) for c in cabinets[2:]] == [
        (0, 0, 0),
        (0, 0, 0),
    ]


def test_nothing_stored_nothing_listed(store: GraphStore) -> None:
    assert get_cabinets(store) == []
    assert cabinets_with_posts(store) == []
    assert get_cabinet(store, "jetten") is None
    assert get_commitment(store, "k1") is None
    assert get_commitments(store) == {
        "total": 0,
        "items": [],
        "facets": {"status": [], "cabinet": [], "ministry": []},
    }


def test_a_cabinet_with_its_members_and_what_they_signed(
    government: GraphStore,
) -> None:
    jetten = get_cabinet(government, "jetten")
    assert jetten is not None
    assert list(jetten) == [
        "cabinet",
        "prime_minister",
        "members",
        "bills",
        "commitments",
    ]
    assert jetten["cabinet"]["props"]["from_date"] == "2026-02-23"
    assert jetten["prime_minister"] == {"key": "m1", "name": "Eelco Heinen"}
    assert (jetten["bills"], jetten["commitments"]) == (1, 3)
    # by edge key; a member that is gone is left out
    assert json.dumps(jetten["members"]) == json.dumps(
        [
            {
                "member": {"key": "m4", "name": "Dirk"},
                "posts": [],
                "dossiers": 0,
                "bills": 0,
                "open_commitments": 0,
            },
            {
                "member": {"key": "m1", "name": "Eelco Heinen"},
                "posts": [{"post": "minister", "ministry": "fin"}],
                # d1 (directly and through the case), d2 and the one that is gone
                "dossiers": 3,
                # of those, the ones stored as government bills
                "bills": 2,
                "open_commitments": 2,
            },
            {
                "member": {"key": "m3", "name": "C. de Vries"},
                "posts": [{"z": 1, "a": 2}],
                "dossiers": 0,
                "bills": 0,
                "open_commitments": 0,
            },
        ]
    )
    # within the period of schoof only what m1 signed before jetten
    schoof = get_cabinet(government, "schoof")
    assert schoof is not None
    assert [
        (m["member"]["key"], m["dossiers"], m["bills"]) for m in schoof["members"]
    ] == [
        ("m2", 0, 0),
        ("m1", 1, 0),
    ]
    assert get_cabinet(government, "nope") is None


def test_a_cabinet_without_a_start_or_an_end(store: GraphStore) -> None:
    today = dt.date.today().isoformat()
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node("open", to_date=""),
            _node("ended", from_date="2000-01-01", to_date="2001-01-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents", [_node("doc", date=today), _node("later", date="9999-01-01")]
    )
    store.bulk_insert_or_update_nodes("members", [_node("m1", name="A")])
    store.bulk_insert_or_update_edges(
        [
            _edge("s1", "members/m1", "cabinets/open", "SERVED_IN"),
            _edge("s2", "members/m1", "cabinets/ended", "SERVED_IN"),
            _edge(
                "a1",
                "members/m1",
                "documents/doc",
                "AUTHORED",
                capacity="bewindspersoon",
            ),
            _edge(
                "a2",
                "members/m1",
                "documents/later",
                "AUTHORED",
                capacity="bewindspersoon",
            ),
            _edge("p1", "documents/doc", "dossiers/d1", "PART_OF"),
            _edge("p2", "documents/later", "dossiers/d2", "PART_OF"),
        ]
    )
    # from any day to today: the document of today counts, the one after it does not
    cabinet = get_cabinet(store, "open")
    assert cabinet is not None and cabinet["prime_minister"] is None
    assert [(m["posts"], m["dossiers"]) for m in cabinet["members"]] == [([], 1)]
    ended = get_cabinet(store, "ended")
    assert ended is not None and ended["members"][0]["dossiers"] == 0


def _keys(page: dict[str, Any]) -> list[str]:
    return [item["commitment"]["_key"] for item in page["items"]]


def test_the_commitments_newest_first_with_their_facets(
    government: GraphStore,
) -> None:
    page = get_commitments(government)
    assert list(page) == ["total", "items", "facets"]
    assert page["total"] == 4
    # the day made, newest first; the key settles a day; undated last
    assert _keys(page) == ["k2", "k1", "k3", "k4"]
    assert json.dumps(page["facets"]) == json.dumps(
        {
            "status": [
                {"value": "Openstaand", "count": 3},
                {"value": "Afgedaan", "count": 1},
            ],
            "cabinet": [
                {"value": "jetten", "count": 3},
                {"value": "schoof", "count": 1},
            ],
            # a tie of counts: by value, null first
            "ministry": [{"value": None, "count": 2}, {"value": "fin", "count": 2}],
        }
    )
    k1 = page["items"][1]
    assert list(k1) == ["commitment", "member", "dossiers", "activity"]
    assert list(k1["commitment"]) == ["_key", "_id", "type", "labels", "props"]
    assert k1["commitment"]["props"]["text"] == "Een brief over Box 3"
    assert json.dumps(k1["member"]) == json.dumps({"key": "m1", "name": "Eelco Heinen"})
    # by label, null first; the first activity by id that is there
    assert json.dumps(k1["dossiers"]) == json.dumps(
        [
            {"key": "d3", "number": None, "title": None},
            {"key": "d1", "number": "36000", "title": "T1"},
        ]
    )
    assert json.dumps(k1["activity"]) == json.dumps(
        {"key": "a1", "date": "2026-04-01", "number": "2026A01"}
    )
    k3 = page["items"][2]
    assert (k3["member"], k3["activity"]) == (None, None)
    assert get_commitment(government, "k1") == k1
    assert get_commitment(government, "nope") is None


def test_each_facet_counts_without_its_own_filter(government: GraphStore) -> None:
    page = get_commitments(government, status="Openstaand", ministry="fin")
    assert page["total"] == 2 and _keys(page) == ["k2", "k1"]
    assert page["facets"] == {
        "status": [{"value": "Openstaand", "count": 2}],
        "cabinet": [{"value": "jetten", "count": 2}],
        "ministry": [{"value": "fin", "count": 2}, {"value": None, "count": 1}],
    }


@pytest.mark.parametrize(
    ("filters", "keys"),
    [
        ({"member": "m1"}, ["k2", "k1"]),
        ({"cabinet": "schoof"}, ["k3"]),
        # a dossier by its number or its label
        ({"dossier": "36000"}, ["k1", "k3"]),
        ({"dossier": "36000-VII"}, ["k3"]),
        ({"dossier": "36001"}, ["k4"]),
        ({"dossier": "1"}, []),
        # expected before a day: one without an expected date passes, as null is lowest
        ({"due_before": "2024-01-01"}, ["k1", "k4"]),
        ({"overdue": True}, ["k1", "k4"]),
        ({"q": "BOX"}, ["k1"]),
        ({"q": "école"}, ["k3"]),
        ({"q": "ECOLE"}, ["k3"]),  # without its accent, in capitals
        # spaces alone find nothing
        ({"q": "   "}, []),
        # soonest due first; without a date (or the placeholder of none) last
        ({"sort": "expected_resolution"}, ["k1", "k3", "k4", "k2"]),
        ({"sort": "expected_resolution", "limit": 2, "offset": 1}, ["k3", "k4"]),
        ({"limit": 2, "offset": 2}, ["k3", "k4"]),
        ({"limit": 2, "offset": 10}, []),
    ],
)
def test_the_commitment_filters(
    government: GraphStore, filters: dict[str, Any], keys: list[str]
) -> None:
    page = get_commitments(government, **filters)
    assert _keys(page) == keys
    if "limit" not in filters:
        assert page["total"] == len(keys)


def test_the_posts_of_every_cabinet_oldest_first(government: GraphStore) -> None:
    rows = cabinets_with_posts(government)
    assert [r["key"] for r in rows] == ["old", "schoof", "tie", "jetten"]
    assert all(list(r) == ["key", "props", "posts"] for r in rows)
    jetten = rows[3]
    assert jetten["props"]["prime_minister"] == "m1"
    # by edge key, each post in its order; MERGE(post, {member, own}): the keys of the
    # post in byte order, then own and member
    assert json.dumps(jetten["posts"]) == json.dumps(
        [
            {"p": 1, "own": False, "member": "ghost"},
            {"ministry": "fin", "post": "minister", "own": False, "member": "m1"},
            {"a": 2, "z": 1, "own": True, "member": "m3"},
        ]
    )
    assert json.dumps(rows[1]["posts"]) == json.dumps(
        [
            {"post": "minister", "own": False, "member": "m2"},
            {"member": "m1", "seat": "y", "own": False},
        ]
    )
    assert rows[0]["posts"] == []


def test_a_cabinet_is_read_once_per_data_version(
    store: GraphStore, monkeypatch
) -> None:
    """The counts read every paper its members signed: kept until the data changes."""
    from lawgraph.db.queries import cabinets

    read: list[str] = []
    real = cabinets._cabinet

    def counted(store_: GraphStore, key: str, today: str):  # type: ignore[no-untyped-def]
        read.append(key)
        return real(store_, key, today)

    monkeypatch.setattr(cabinets, "_cabinet", counted)
    assert cabinets.get_cabinet(store, "schoof") is None
    assert cabinets.get_cabinet(store, "schoof") is None
    assert read == ["schoof"]


def test_a_cabinet_is_kept_an_hour_whatever_the_data_does(
    government: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll of other sources raises the data version: the page of a cabinet is not
    computed again for it within ``CABINET_MAX_AGE`` (its counts read every paper its
    members signed); after it, it is."""
    from lawgraph.db import version_cache
    from lawgraph.db.queries import cabinets as cabinet_queries

    version_cache.clear()
    computed: list[str] = []
    compute = cabinet_queries._cabinet

    def counted(store: GraphStore, key: str, today: str) -> Any:
        computed.append(key)
        return compute(store, key, today)

    monkeypatch.setattr(cabinet_queries, "_cabinet", counted)
    before = get_cabinet(government, "jetten")
    assert before is not None and before["commitments"] == 3
    version = government.data_version()
    government.bulk_insert_or_update_nodes(
        "commitments",
        [_node("k9", member_key="m1", cabinet="jetten", status="Openstaand")],
    )
    assert government.data_version() != version
    monkeypatch.setattr(version_cache, "VERSION_TTL", 0.0)  # the new version is seen
    assert get_cabinet(government, "jetten") == before
    assert computed == ["jetten"]

    monkeypatch.setattr(cabinet_queries, "CABINET_MAX_AGE", 0.0)
    assert get_cabinet(government, "jetten")["commitments"] == 4  # type: ignore[index]
    assert computed == ["jetten", "jetten"]


def test_the_commitments_without_facets_the_page_and_the_total_alone(
    government: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``facets=False``: the same page and total, ``facets`` None, and no facet counted."""
    with_facets = get_commitments(government, status="Openstaand", limit=1)
    statements: list[str] = []
    query = government.query

    def counting(statement: Any, params: Any = None, **options: Any) -> Any:
        statements.append(str(statement))
        return query(statement, params, **options)

    monkeypatch.setattr(government, "query", counting)
    without = get_commitments(government, status="Openstaand", limit=1, facets=False)
    assert without == {**with_facets, "facets": None}
    assert statements and not [s for s in statements if "GROUP BY" in s]
