"""The dossier hub, the committee pages and the authorship lists, run for real.

Each test writes the small graph it needs (nodes and edges as the pipelines write them) and
asks the queries behind the endpoints, so a wrong traversal or a wrong edge direction shows.
The scale test builds a dossier that a big amending law would give.
"""

from __future__ import annotations

import time
from typing import Any

from lawgraph.api.queries.committees import (
    get_actor_dossiers,
    get_committee_activities,
    get_committee_detail,
)
from lawgraph.api.queries.dossiers import get_dossier_hub
from lawgraph.config.constants import (
    EDGE_STATUS_VOORGESTELD,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_AUTHORED,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_LEGISLATED_IN,
    RELATION_MEMBER_OF,
    RELATION_PART_OF,
    RELATION_REPEALS,
)
from lawgraph.db import ArangoStore, make_edge_doc


class Graph:
    """Nodes and edges written straight into the test database."""

    def __init__(self, store: ArangoStore) -> None:
        self.store = store
        self._nodes: dict[str, list[dict[str, Any]]] = {}
        self._edges: list[dict[str, Any]] = []

    def node(
        self, collection: str, key: str, labels: list[str] | None = None, **props: Any
    ) -> str:
        self._nodes.setdefault(collection, []).append(
            {
                "_key": key,
                "type": collection[:-1],
                "labels": labels or [],
                "props": props,
            }
        )
        return f"{collection}/{key}"

    def edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        *,
        status: str = "canoniek",
        **meta: Any,
    ) -> None:
        self._edges.append(
            make_edge_doc(from_id, to_id, relation, status=status, meta=meta)
        )

    def write(self) -> None:
        for collection, docs in self._nodes.items():
            self.store.bulk_insert_or_update_nodes(collection, docs)
        self.store.bulk_insert_or_update_edges(self._edges)
        self._nodes, self._edges = {}, []


def _hub_graph(store: ArangoStore) -> None:
    g = Graph(store)
    dossier = g.node("dossiers", "36001", number="36001", closed=False)
    other = g.node("dossiers", "36002", number="36002", closed=False)
    case = g.node("cases", "case1", title="Zaak")

    # A regulation that came out of the dossier, one that only an amending publication
    # touched, an EU act, and a law nothing links to the dossier.
    law_a = g.node(
        "instruments",
        "bwbr0000001",
        bwb_id="BWBR0000001",
        display_name="Wet A",
        jurisdiction="nl",
    )
    law_b = g.node(
        "instruments",
        "bwbr0000002",
        bwb_id="BWBR0000002",
        display_name="Wet B",
        jurisdiction="nl",
    )
    law_c = g.node(
        "instruments",
        "bwbr0000003",
        bwb_id="BWBR0000003",
        display_name="Wet C",
        jurisdiction="nl",
    )
    directive = g.node(
        "instruments",
        "32016l0680",
        celex="32016L0680",
        display_name="Richtlijn X",
        jurisdiction="eu",
    )
    unrelated = g.node(
        "instruments",
        "bwbr0000009",
        bwb_id="BWBR0000009",
        display_name="Wet Z",
        jurisdiction="nl",
    )
    parents = {
        "bwbr0000001_5": law_a,
        "bwbr0000002_1": law_b,
        "bwbr0000002_2": law_b,
        "bwbr0000002_3": law_b,
        "bwbr0000003_1": law_c,
        "32016l0680_4": directive,
        "bwbr0000009_1": unrelated,
    }
    articles = {}
    for name, parent in parents.items():
        articles[name] = g.node("articles", name)
        g.edge(articles[name], RELATION_PART_OF, parent)

    g.edge(law_a, RELATION_LEGISLATED_IN, dossier)
    publication = g.node(
        "instruments", "stb_2020_1", publication_kind="Stb", display_name="Stb. 2020, 1"
    )
    elsewhere = g.node(
        "instruments", "stb_2020_2", publication_kind="Stb", display_name="Stb. 2020, 2"
    )
    g.edge(publication, RELATION_LEGISLATED_IN, dossier)
    g.edge(publication, RELATION_AMENDS, articles["bwbr0000002_1"])
    g.edge(
        publication, RELATION_AMENDS, articles["bwbr0000002_2"]
    )  # same law: one item
    g.edge(publication, RELATION_INTRODUCES, articles["bwbr0000002_3"])
    g.edge(
        publication, RELATION_AMENDS, articles["bwbr0000001_5"]
    )  # also legislated_in
    g.edge(publication, RELATION_REPEALS, articles["32016l0680_4"])
    g.edge(elsewhere, RELATION_LEGISLATED_IN, other)
    g.edge(elsewhere, RELATION_AMENDS, articles["bwbr0000009_1"])

    # Bills of the dossier: one direct, one through a case. Each proposes changes.
    motion = g.node(
        "documents", "d1", ["TK"], kind="Motie", date="2024-01-05", title="Motie"
    )
    amendment = g.node(
        "documents",
        "d2",
        ["TK"],
        kind="Amendement",
        date="2024-02-01",
        title="Amendement",
    )
    untyped = g.node("documents", "d3", ["TK"], kind="", date="2024-03-01")
    ek_late = g.node(
        "documents", "ek_2", ["EersteKamer", "EK"], kind="Brief", date="2024-05-01"
    )
    ek_early = g.node(
        "documents", "ek_1", ["EersteKamer", "EK"], kind="Brief", date="2024-04-01"
    )
    ek_other = g.node("documents", "ek_9", ["EK"], kind="Brief", date="2020-01-01")
    g.edge(motion, RELATION_PART_OF, dossier)
    g.edge(amendment, RELATION_PART_OF, case)
    g.edge(case, RELATION_PART_OF, dossier)
    g.edge(untyped, RELATION_PART_OF, dossier)
    g.edge(ek_late, RELATION_PART_OF, dossier)
    g.edge(ek_early, RELATION_PART_OF, dossier)
    g.edge(ek_other, RELATION_PART_OF, other)
    g.edge(
        motion, RELATION_AMENDS, law_c, status=EDGE_STATUS_VOORGESTELD
    )  # the instrument
    g.edge(
        amendment,
        RELATION_INTRODUCES,
        articles["bwbr0000003_1"],
        status=EDGE_STATUS_VOORGESTELD,
    )
    g.edge(
        amendment,
        RELATION_AMENDS,
        articles["bwbr0000002_1"],
        status=EDGE_STATUS_VOORGESTELD,
    )

    # Committees: an activity about the dossier, one about its case, a plenary one and one
    # about another dossier.
    lead_a = g.node(
        "committees", "c_a", name="Commissie A", slug="a", abbreviation="CA"
    )
    lead_b = g.node("committees", "c_b", name="Commissie B", slug="b")
    lead_c = g.node("committees", "c_c", name="Commissie C", slug="c")
    for key, about, committee in (
        ("act1", dossier, lead_a),
        ("act2", case, lead_b),
        ("act3", dossier, None),
        ("act4", other, lead_c),
    ):
        activity = g.node("activities", key, date="2024-06-01", kind="Commissiedebat")
        g.edge(activity, RELATION_ABOUT, about)
        if committee:
            g.edge(activity, RELATION_LED_BY, committee)
    both = g.node("activities", "act5", date="2024-06-02", kind="Commissiedebat")
    g.edge(both, RELATION_ABOUT, dossier)
    g.edge(both, RELATION_ABOUT, case)
    g.edge(both, RELATION_LED_BY, lead_a)
    g.write()


def test_the_hub_gathers_instruments_committees_and_documents_in_one_query(
    database: str,
) -> None:
    store = ArangoStore()
    _hub_graph(store)

    asked: list[str] = []
    real = store.query

    def recording(aql: str, *args: Any, **kwargs: Any) -> Any:
        asked.append(aql)
        return real(aql, *args, **kwargs)

    store.query = recording  # type: ignore[method-assign]
    hub = get_dossier_hub(store, "dossiers/36001")
    assert len(asked) == 1

    rows = [(i["display_name"], i["relation"], i["status"]) for i in hub["instruments"]]
    assert rows == [
        ("Wet A", "legislated_in", "canoniek"),
        ("Wet A", "amends", "canoniek"),
        ("Wet B", "amends", "canoniek"),
        ("Wet B", "amends", "voorgesteld"),
        ("Wet C", "amends", "voorgesteld"),
        ("Wet B", "introduces", "canoniek"),
        ("Wet C", "introduces", "voorgesteld"),
        ("Richtlijn X", "repeals", "canoniek"),
    ]
    by_key = {(i["key"], i["relation"]): i for i in hub["instruments"]}
    assert by_key[("bwbr0000001", "legislated_in")]["bwb_id"] == "BWBR0000001"
    assert by_key[("bwbr0000001", "legislated_in")]["jurisdiction"] == "nl"
    assert by_key[("32016l0680", "repeals")]["celex"] == "32016L0680"
    assert by_key[("32016l0680", "repeals")]["bwb_id"] is None
    assert not any(key == "bwbr0000009" for key, _ in by_key)  # another dossier's
    assert len(rows) == len(set(rows))  # one item per (instrument, relation, status)

    assert [c["slug"] for c in hub["committees"]] == [
        "a",
        "b",
    ]  # once, plenary and other left out
    assert hub["committees"][0]["abbreviation"] == "CA"

    assert hub["documents_by_kind"] == {
        "Motie": 1,
        "Amendement": 1,
        "Brief": 2,
    }  # the case's document counts, the untyped one and another dossier's do not
    assert hub["senate"] == {"document_count": 2, "first_date": "2024-04-01"}


def test_a_dossier_without_links_has_an_empty_hub(database: str) -> None:
    store = ArangoStore()
    g = Graph(store)
    g.node("dossiers", "36003", number="36003")
    g.write()

    hub = get_dossier_hub(store, "dossiers/36003")

    assert hub == {
        "instruments": [],
        "committees": [],
        "documents_by_kind": {},
        "senate": {"document_count": 0, "first_date": None},
    }


def test_the_hub_of_a_big_amending_law_walks_indexes_and_stays_fast(
    database: str,
) -> None:
    """One publication that amends 3,000 articles of 300 laws, and 600 documents."""
    store = ArangoStore()
    g = Graph(store)
    dossier = g.node("dossiers", "36004", number="36004")
    publication = g.node("instruments", "stb_2021_9", publication_kind="Stb")
    g.edge(publication, RELATION_LEGISLATED_IN, dossier)
    for law in range(300):
        instrument = g.node(
            "instruments",
            f"bwbr{law:07d}",
            bwb_id=f"BWBR{law:07d}",
            display_name=f"Wet {law}",
        )
        for number in range(10):
            article = g.node("articles", f"bwbr{law:07d}_{number}")
            g.edge(article, RELATION_PART_OF, instrument)
            g.edge(publication, RELATION_AMENDS, article)
    for number in range(600):
        document = g.node(
            "documents", f"doc{number}", ["TK"], kind="Motie", date="2024-01-01"
        )
        g.edge(document, RELATION_PART_OF, dossier)
    g.write()

    started = time.monotonic()
    hub = get_dossier_hub(store, "dossiers/36004")
    elapsed = time.monotonic() - started

    assert len(hub["instruments"]) == 300
    assert hub["documents_by_kind"] == {"Motie": 600}
    assert elapsed < 2.0, elapsed

    from lawgraph.api.queries import dossiers

    body = dossiers._dossier_documents_aql(dossiers._DOSSIER_HUB_BODY)
    aql = f"LET dossier_id = @dossier_id\n{body}"
    plan = store.db.aql.explain(
        aql,
        bind_vars={
            "dossier_id": "dossiers/36004",
            "part_of": RELATION_PART_OF,
            "about": RELATION_ABOUT,
            "led_by": RELATION_LED_BY,
            "legislated_in": RELATION_LEGISLATED_IN,
            "changes": [RELATION_AMENDS],
            "canonical": "canoniek",
            "relation_order": ["legislated_in", "amends"],
        },
    )
    kinds = {node["type"] for node in plan["nodes"]}
    assert "EnumerateCollectionNode" not in kinds


def test_the_committee_pages_dossiers_by_status_and_lists_its_activities(
    database: str,
) -> None:
    store = ArangoStore()
    g = Graph(store)
    committee = g.node("committees", "c_a", name="Commissie A", slug="a")
    other = g.node("committees", "c_b", name="Commissie B", slug="b")
    for number in range(5):
        closed = number >= 3
        dossier = g.node(
            "dossiers",
            f"3700{number}",
            number=f"3700{number}",
            closed=closed,
            opened_on=f"2024-0{number + 1}-01",
        )
        activity = g.node(
            "activities",
            f"a{number}",
            date=f"2024-0{number + 1}-10",
            kind="Commissiedebat",
            agenda_title=f"Debat {number}",
            dossier_numbers=[f"3700{number}"],
        )
        g.edge(activity, RELATION_ABOUT, dossier)
        g.edge(activity, RELATION_LED_BY, committee)
    stray = g.node("activities", "stray", date="2025-01-01", kind="Hoorzitting")
    g.edge(stray, RELATION_LED_BY, other)
    g.write()

    everything = get_committee_detail(store, "a", limit=2)
    assert everything is not None
    assert everything["dossier_total"] == 5 and everything["open_dossier_count"] == 3
    assert [d["_key"] for d in everything["dossiers"]] == [
        "37004",
        "37003",
    ]  # newest opened

    second = get_committee_detail(store, "A", limit=2, offset=2)
    assert second is not None
    assert [d["_key"] for d in second["dossiers"]] == ["37002", "37001"]

    closed = get_committee_detail(store, "a", status="closed")
    assert closed is not None
    assert closed["dossier_total"] == 2 and closed["open_dossier_count"] == 3
    assert {d["_key"] for d in closed["dossiers"]} == {"37003", "37004"}

    opened = get_committee_detail(store, "a", status="open")
    assert opened is not None
    assert opened["dossier_total"] == 3
    assert {d["_key"] for d in opened["dossiers"]} == {"37000", "37001", "37002"}

    assert get_committee_detail(store, "nope") is None

    page = get_committee_activities(store, "a", limit=2)
    assert page is not None and page["total"] == 5
    assert [row["key"] for row in page["items"]] == ["a4", "a3"]  # newest first
    assert page["items"][0] == {
        "id": "activities/a4",
        "key": "a4",
        "date": "2024-05-10",
        "kind": "Commissiedebat",
        "agenda_title": "Debat 4",
        "dossier_numbers": ["37004"],
    }
    rest = get_committee_activities(store, "a", limit=2, offset=4)
    assert rest is not None and [row["key"] for row in rest["items"]] == ["a0"]
    assert get_committee_activities(store, "nope") is None


def _authorship_graph(store: ArangoStore) -> None:
    g = Graph(store)
    vvd = g.node("factions", "vvd", abbreviation="VVD", name="VVD")
    d66 = g.node("factions", "d66", abbreviation="D66", name="D66")
    switcher = g.node(
        "members",
        "m1",
        name="Wisselaar",
        faction_memberships=[
            {"faction_id": vvd, "from_date": "2010-01-01", "to_date": "2019-12-31"},
            {"faction_id": d66, "from_date": "2020-01-01", "to_date": None},
        ],
    )
    loyal = g.node(
        "members",
        "m2",
        name="Trouw",
        faction_memberships=[
            {"faction_id": vvd, "from_date": "2010-01-01", "to_date": None}
        ],
    )
    g.edge(switcher, RELATION_MEMBER_OF, vvd)
    g.edge(switcher, RELATION_MEMBER_OF, d66)
    g.edge(loyal, RELATION_MEMBER_OF, vvd)

    direct = g.node("dossiers", "38001", number="38001", opened_on="2015-01-01")
    through_case = g.node("dossiers", "38002", number="38002", opened_on="2021-01-01")
    untouched = g.node("dossiers", "38003", number="38003", opened_on="2022-01-01")
    case = g.node("cases", "zaak1")
    g.edge(case, RELATION_PART_OF, through_case)
    g.edge(g.node("documents", "unrelated"), RELATION_PART_OF, untouched)

    def document(key: str, date: str, parent: str) -> str:
        doc = g.node("documents", key, ["TK"], kind="Motie", date=date)
        g.edge(doc, RELATION_PART_OF, parent)
        return doc

    old_motion = document("old", "2015-06-01", direct)  # signed as VVD
    old_extra = document("old2", "2015-07-01", direct)
    new_motion = document(
        "new", "2021-06-01", case
    )  # signed as D66, dossier through a case
    g.edge(switcher, RELATION_AUTHORED, old_motion, role="Eerste ondertekenaar")
    g.edge(switcher, RELATION_AUTHORED, old_extra, role="Mede ondertekenaar")
    g.edge(switcher, RELATION_AUTHORED, new_motion, role="Eerste ondertekenaar")
    g.edge(loyal, RELATION_AUTHORED, old_extra, role="Mede ondertekenaar")
    g.write()


def test_a_member_and_a_faction_list_the_dossiers_they_authored_in(
    database: str,
) -> None:
    store = ArangoStore()
    _authorship_graph(store)

    member = get_actor_dossiers(store, "members/m1")
    assert member["total"] == 2
    first, second = member["items"]  # newest opened first
    assert first["dossier"]["_key"] == "38002"
    assert first["roles"] == ["Eerste ondertekenaar"] and first["document_count"] == 1
    assert second["dossier"]["_key"] == "38001"
    assert second["roles"] == ["Eerste ondertekenaar", "Mede ondertekenaar"]
    assert second["document_count"] == 2

    page = get_actor_dossiers(store, "members/m1", limit=1, offset=1)
    assert page["total"] == 2 and [r["dossier"]["_key"] for r in page["items"]] == [
        "38001"
    ]

    # A faction counts what its members signed while they belonged to it.
    vvd = get_actor_dossiers(store, "factions/vvd")
    assert vvd["total"] == 1
    assert vvd["items"][0]["dossier"]["_key"] == "38001"
    assert vvd["items"][0]["document_count"] == 2  # both old motions, by two members
    assert vvd["items"][0]["roles"] == ["Eerste ondertekenaar", "Mede ondertekenaar"]

    d66 = get_actor_dossiers(store, "factions/d66")
    assert d66["total"] == 1 and d66["items"][0]["dossier"]["_key"] == "38002"

    assert get_actor_dossiers(store, "members/nobody") == {"total": 0, "items": []}


def test_a_big_faction_and_a_busy_committee_answer_in_one_query_each(
    database: str,
) -> None:
    """60 members who each signed 250 motions in 50 dossiers, and 3,000 debates."""
    store = ArangoStore()
    g = Graph(store)
    faction = g.node("factions", "vvd", abbreviation="VVD")
    committee = g.node("committees", "c_a", name="Commissie A", slug="a")
    dossiers = [
        g.node("dossiers", f"39{n:03d}", number=f"39{n:03d}", opened_on="2024-01-01")
        for n in range(50)
    ]
    for member in range(60):
        person = g.node(
            "members",
            f"m{member}",
            faction_memberships=[
                {"faction_id": faction, "from_date": "2000-01-01", "to_date": None}
            ],
        )
        g.edge(person, RELATION_MEMBER_OF, faction)
        for number in range(250):
            document = g.node(
                "documents",
                f"m{member}_d{number}",
                ["TK"],
                kind="Motie",
                date="2024-01-01",
            )
            g.edge(document, RELATION_PART_OF, dossiers[number % 50])
            g.edge(person, RELATION_AUTHORED, document, role="Eerste ondertekenaar")
    for number in range(3000):
        activity = g.node(
            "activities",
            f"act{number}",
            date=f"2024-01-{number % 28 + 1:02d}",
            kind="Debat",
        )
        g.edge(activity, RELATION_LED_BY, committee)
    g.write()

    started = time.monotonic()
    result = get_actor_dossiers(store, faction, limit=10)
    faction_seconds = time.monotonic() - started
    started = time.monotonic()
    page = get_committee_activities(store, "a", limit=10, offset=100)
    committee_seconds = time.monotonic() - started

    assert result["total"] == 50 and len(result["items"]) == 10
    assert (
        result["items"][0]["document_count"] == 300
    )  # 15,000 documents over 50 dossiers
    assert page is not None and page["total"] == 3000 and len(page["items"]) == 10
    assert faction_seconds < 5.0 and committee_seconds < 2.0, (
        faction_seconds,
        committee_seconds,
    )


def test_the_routes_answer_from_the_real_graph(database: str) -> None:
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store
    from lawgraph.api.routes import committees as committee_routes

    store = ArangoStore()
    _hub_graph(store)
    _authorship_graph(store)
    committee_routes._faction_dossiers_cache.clear()
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        hub = client.get("/api/dossiers/36001").json()
        assert hub["number"] == "36001" and hub["documents_by_kind"]["Amendement"] == 1
        assert hub["instruments"][0]["relation"] == "legislated_in"
        assert [c["slug"] for c in hub["committees"]] == ["a", "b"]
        assert hub["senate"]["first_date"] == "2024-04-01"

        activities = client.get("/api/committees/a/activities?limit=1").json()
        assert activities["total"] == 2 and activities["items"][0]["key"] == "act5"
        assert client.get("/api/committees/a?status=open").json()["dossier_total"] == 1

        member = client.get("/api/members/m1/dossiers").json()
        assert member["actor_id"] == "members/m1" and member["total"] == 2
        assert member["items"][0]["number"] == "38002"
        faction = client.get("/api/factions/vvd/dossiers").json()
        assert faction["total"] == 1 and faction["items"][0]["document_count"] == 2
    finally:
        app.dependency_overrides.pop(get_store, None)
        committee_routes._faction_dossiers_cache.clear()
