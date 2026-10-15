"""The cabinet and commitment queries on a real PostgreSQL: the cabinets with their counts,
a cabinet with its bewindspersonen, the commitments with their facets, and the posts that
``verify cabinets`` reads."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import member_authored
from lawgraph.db.queries.cabinets import cabinets_with_posts, get_cabinet, get_cabinets
from lawgraph.db.queries.commitments import get_commitment, get_commitments
from tests.optional import present
from tests.pg.cabinet_graph import edge, government_graph, node
from tests.pg.plans import explain, plan_nodes, recorded


@pytest.fixture()
def government(store: GraphStore) -> GraphStore:
    government_graph(store)
    return store


def test_the_cabinets_newest_first_with_their_counts(government: GraphStore) -> None:
    cabinets = get_cabinets(government)
    assert [c["cabinet"]["key"] for c in cabinets] == [
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
    assert jetten["cabinet"]["id"] == "cabinets/jetten"
    assert json.dumps(jetten["prime_minister"]) == json.dumps(
        {"key": "m1", "name": "Eelco Heinen", "slug": "eelco-heinen"}
    )
    # every SERVED_IN edge; the government bills; the commitments made under it
    assert (jetten["members"], jetten["bills"], jetten["commitments"]) == (4, 1, 3)
    schoof = cabinets[1]
    assert schoof["prime_minister"] == {"key": "m2", "name": "Bert", "slug": None}
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
    assert jetten["prime_minister"] == {
        "key": "m1",
        "name": "Eelco Heinen",
        "slug": "eelco-heinen",
    }
    assert (jetten["bills"], jetten["commitments"]) == (1, 3)
    # by edge key; a member that is gone is left out
    assert json.dumps(jetten["members"]) == json.dumps(
        [
            {
                "member": {"key": "m4", "name": "Dirk", "slug": None},
                "posts": [],
                "dossiers": 0,
                "bills": 0,
                "open_commitments": 0,
            },
            {
                "member": {"key": "m1", "name": "Eelco Heinen", "slug": "eelco-heinen"},
                "posts": [{"post": "minister", "ministry": "fin"}],
                # d1 (directly and through the case), d2 and the one that is gone
                "dossiers": 3,
                # of those, the ones stored as government bills
                "bills": 2,
                "open_commitments": 2,
            },
            {
                "member": {"key": "m3", "name": "C. de Vries", "slug": None},
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


def test_what_its_members_signed_after_a_fill_is_the_same(
    government: GraphStore,
) -> None:
    """A fill of an empty ``lg_authored`` (one written before the triggers) gives the same
    counts as the triggers kept: the paper counted directly and through its case, the
    dossier that is gone, the period of each cabinet."""
    kept = {key: get_cabinet(government, key) for key in ("jetten", "schoof")}
    government.execute("DELETE FROM lg_authored")  # as written before the triggers
    member_authored.fill_authored(government)
    version_cache.clear()
    filled = {key: get_cabinet(government, key) for key in ("jetten", "schoof")}
    assert json.dumps(filled) == json.dumps(kept)
    # and it is what is read: a paper kept with another dossier counts that one
    government.execute(
        "UPDATE lg_authored SET dossiers = ARRAY['dossiers/elsewhere']"
        " WHERE member_id = 'members/m1'"
    )
    version_cache.clear()
    jetten = get_cabinet(government, "jetten")
    assert jetten is not None
    (heinen,) = [m for m in jetten["members"] if m["member"]["key"] == "m1"]
    assert (heinen["dossiers"], heinen["bills"]) == (1, 0)


def test_a_case_signed_directly_counts_by_its_own_date(government: GraphStore) -> None:
    """A bewindspersoon's AUTHORED edge to a case (most of an old minister's signatures)
    counts its dossier when the case's own date falls within the cabinet."""
    government.bulk_insert_or_update_nodes(
        "cases", [node("c2", date="2026-03-05"), node("c3", date="2020-01-01")]
    )
    government.bulk_insert_or_update_edges(
        [
            edge("a7", "members/m4", "cases/c2", "AUTHORED", capacity="bewindspersoon"),
            edge("a8", "members/m4", "cases/c3", "AUTHORED", capacity="bewindspersoon"),
            edge("p9", "cases/c2", "dossiers/d4", "PART_OF"),
            edge("p10", "cases/c3", "dossiers/d1", "PART_OF"),
        ]
    )

    def dirk() -> tuple[int, int]:
        version_cache.clear()
        jetten = get_cabinet(government, "jetten")
        assert jetten is not None
        (m4,) = [m for m in jetten["members"] if m["member"]["key"] == "m4"]
        return m4["dossiers"], m4["bills"]

    # d4 through the case of 2026; the case of 2020 is before jetten
    assert dirk() == (1, 1)


def test_what_its_members_signed_read_by_date_reads_no_paper(
    government: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counts of a member are a range of the index of ``lg_authored`` by capacity and
    date: no paper or case read for its date (a minister of many cabinets signed tens of
    thousands, a probe each)."""
    calls = recorded(government, monkeypatch)
    for key in ("jetten", "schoof"):
        assert get_cabinet(government, key) is not None

    statement, params, *_ = [c for c in calls if c.params and "served_in" in c.params][
        0
    ]
    plan = explain(government, statement, params)
    relations = {n["Relation Name"] for n in plan_nodes(plan) if "Relation Name" in n}
    assert not relations & {"documents", "cases"}
    # and the date is what is read: a signature dated before jetten leaves it
    government.execute(
        "UPDATE lg_authored SET date = '2000-01-01' WHERE member_id = 'members/m1'"
    )
    version_cache.clear()
    jetten = get_cabinet(government, "jetten")
    assert jetten is not None
    (heinen,) = [m for m in jetten["members"] if m["member"]["key"] == "m1"]
    assert (heinen["dossiers"], heinen["bills"]) == (0, 0)


def test_a_cabinet_without_a_start_or_an_end(store: GraphStore) -> None:
    today = dt.date.today().isoformat()
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            node("open", to_date=""),
            node("ended", from_date="2000-01-01", to_date="2001-01-01"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents", [node("doc", date=today), node("later", date="9999-01-01")]
    )
    store.bulk_insert_or_update_nodes("members", [node("m1", name="A")])
    store.bulk_insert_or_update_edges(
        [
            edge("s1", "members/m1", "cabinets/open", "SERVED_IN"),
            edge("s2", "members/m1", "cabinets/ended", "SERVED_IN"),
            edge(
                "a1",
                "members/m1",
                "documents/doc",
                "AUTHORED",
                capacity="bewindspersoon",
            ),
            edge(
                "a2",
                "members/m1",
                "documents/later",
                "AUTHORED",
                capacity="bewindspersoon",
            ),
            edge("p1", "documents/doc", "dossiers/d1", "PART_OF"),
            edge("p2", "documents/later", "dossiers/d2", "PART_OF"),
        ]
    )
    # from any day to today: the document of today counts, the one after it does not
    cabinet = get_cabinet(store, "open")
    assert cabinet is not None and cabinet["prime_minister"] is None
    assert [(m["posts"], m["dossiers"]) for m in cabinet["members"]] == [([], 1)]
    ended = get_cabinet(store, "ended")
    assert ended is not None and ended["members"][0]["dossiers"] == 0


def _keys(page: dict[str, Any]) -> list[str]:
    return [item["commitment"]["key"] for item in page["items"]]


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
    assert list(k1) == ["commitment", "member", "dossiers", "activity", "fulfilled_by"]
    assert list(k1["commitment"]) == ["key", "id", "type", "labels", "props"]
    assert k1["commitment"]["props"]["text"] == "Een brief over Box 3"
    assert json.dumps(k1["member"]) == json.dumps(
        {"key": "m1", "name": "Eelco Heinen", "slug": "eelco-heinen"}
    )
    # by label, null first; the first activity by id that is there
    assert json.dumps(k1["dossiers"]) == json.dumps(
        [
            {"key": "d3", "number": None, "title": None},
            {"key": "d1", "number": "36000", "title": "T1"},
        ]
    )
    assert json.dumps(k1["activity"]) == json.dumps(
        {
            "key": "a1",
            "date": "2026-04-01",
            "number": "2026A01",
            "kind": None,
            "agenda_title": None,
        }
    )
    assert k1["fulfilled_by"] == []
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
    # by edge key, each post in its order, with its member and whether only Rijksoverheid
    # knows them
    assert jetten["posts"] == [
        {"p": 1, "own": False, "member": "ghost"},
        {"ministry": "fin", "post": "minister", "own": False, "member": "m1"},
        {"a": 2, "z": 1, "own": True, "member": "m3"},
    ]
    assert rows[1]["posts"] == [
        {"post": "minister", "own": False, "member": "m2"},
        {"member": "m1", "seat": "y", "own": False},
    ]
    assert rows[0]["posts"] == []


def test_a_cabinet_is_read_once_per_data_version(
    store: GraphStore, monkeypatch
) -> None:
    """The counts read every paper its members signed: kept until the data changes."""
    from lawgraph.db.queries import cabinets

    read: list[str] = []
    real = cabinets._cabinet

    def counted(store_: GraphStore, key: str, today: str):
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
        [node("k9", member_key="m1", cabinet="jetten", status="Openstaand")],
    )
    assert government.data_version() != version
    monkeypatch.setattr(version_cache, "VERSION_TTL", 0.0)  # the new version is seen
    assert get_cabinet(government, "jetten") == before
    assert computed == ["jetten"]

    monkeypatch.setattr(cabinet_queries, "CABINET_MAX_AGE", 0.0)
    assert present(get_cabinet(government, "jetten"))["commitments"] == 4
    assert computed == ["jetten", "jetten"]


def test_the_commitments_without_facets_the_page_and_the_total_alone(
    government: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``facets=False``: the same page and total, ``facets`` None, and no facet counted."""
    with_facets = get_commitments(government, status="Openstaand", limit=1)
    calls = recorded(government, monkeypatch)
    without = get_commitments(government, status="Openstaand", limit=1, facets=False)
    statements = [c.text for c in calls]
    assert without == {**with_facets, "facets": None}
    assert statements and not [s for s in statements if "GROUP BY" in s]
