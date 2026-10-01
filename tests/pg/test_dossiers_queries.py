"""The dossier queries on a real PostgreSQL: one dossier, its timeline, its documents, its
hub, its mutations and relations, the counts of its members, the list of dossiers with its
facets, the laws a title names and the values of the Tweede Kamer; some through
``GET /api/dossiers``.

The graphs are written by hand, so that every path of the SQL has a node to take: a
document PART_OF the dossier directly and through a case, an activity led by a committee
and one without, an amending publication and the bills of the dossier.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.dossiers import timeline_entry
from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_ABOUT,
    RELATION_ACCOMPANIES,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_RELATED_TO,
    RELATION_REPEALS,
    RELATION_REVISES,
    RELATION_VERSION_OF,
)
from lawgraph.core.dossier_numbers import dossier_order
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter, make_edge_doc
from lawgraph.db.queries.dossiers import (
    DossierFilters,
    count_dossier_members,
    get_dossier_by_number,
    get_dossier_documents,
    get_dossier_hub,
    get_dossier_mutations,
    get_dossier_relations,
    get_dossier_timeline,
    get_dossiers,
    get_laws_named,
    tk_values,
)
from lawgraph.db.queries.normalize import tk as normalize_tk

# ── dossier documents and timeline ──

DOSSIER = f"{COLLECTION_DOSSIERS}/36000"
LONG_TEXT = "Artikel 5 wordt gewijzigd. " * 400


def _node(
    collection: str,
    node_type: NodeType,
    key: str,
    labels: list[str],
    **props: Any,
) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=labels, props=props
    )


def _document(key: str, kind: str, date: str, **props: Any) -> Node:
    return _node(
        COLLECTION_DOCUMENTS,
        NodeType.DOCUMENT,
        key,
        ["TK"],
        source="tk",
        kind=kind,
        title=f"{kind} {key}",
        display_name=f"{kind} {key}",
        date=date,
        text=LONG_TEXT,
        raw={"payload": LONG_TEXT},
        **props,
    )


def _build(store: ArangoStore) -> None:
    """A dossier 36000; a second dossier 36001 that shares none of it."""
    nodes = [
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "36000",
            ["TK"],
            number="36000",
            label="36000",
        ),
        _node(
            COLLECTION_DOSSIERS,
            NodeType.DOSSIER,
            "36001",
            ["TK"],
            number="36001",
            label="36001",
        ),
        _node(COLLECTION_CASES, NodeType.CASE, "case_1", ["TK"], number="2025Z1"),
        # a memorandum PART_OF the dossier itself
        _document(
            "mvt",
            "Memorie van toelichting",
            "2025-01-10",
            sequence=3,
            session_year="2024-2025",
            document_number="2025D00003",
            dossier_numbers=["36000"],
        ),
        # a motion PART_OF the case only, and the case PART_OF the dossier
        _document(
            "motie",
            "Motie",
            "2025-02-10",
            case_ids=["case_1"],
            actors=[
                {"name": "Lid A", "role": "Eerste ondertekenaar", "person_id": "p1"},
                {"name": "Lid B", "role": "Mede ondertekenaar"},
            ],
        ),
        # an Eerste Kamer paper: its own labels, no text, PART_OF the dossier
        _node(
            COLLECTION_DOCUMENTS,
            NodeType.DOCUMENT,
            "ek_1",
            ["EersteKamer", "EK"],
            source="eerstekamer",
            kind="Nota naar aanleiding van het verslag",
            title="Nota EK",
            display_name="EK 36000, nr. 1: Nota EK",
            date="2025-03-01",
            dossier_number="36000",
            number="C",
            url="https://ek.example/1",
        ),
        # a document of another dossier
        _document("other", "Brief", "2025-01-01", dossier_numbers=["36001"]),
        _node(
            COLLECTION_ACTIVITIES,
            NodeType.ACTIVITY,
            "act_committee",
            ["TK"],
            source="tk",
            kind="Commissiedebat",
            agenda_title="2025-03-06 - Debat",
            date="2025-03-06",
            number="2025A1",
            committee_id="c1",
            display_name="Debat",
        ),
        _node(
            COLLECTION_ACTIVITIES,
            NodeType.ACTIVITY,
            "act_plenary",
            ["TK"],
            source="tk",
            kind="Plenair debat",
            date="2025-03-07",
            display_name="Plenair debat",
        ),
        _node(
            COLLECTION_COMMITTEES,
            NodeType.COMMITTEE,
            "c1",
            ["TK"],
            name="Vaste commissie voor Infrastructuur",
            abbreviation="IENW",
            slug="ienw",
        ),
        _node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "stemming_1",
            ["TK"],
            source="tk",
            date="2025-03-08",
            subject="Motie over wegen",
            decision_id="b1",
            passed=True,
            vote_kind="faction",
            tally={"Voor": 80, "Tegen": 70},
            voters={"Voor": 5, "Tegen": 4},
            dossier_numbers=["36000"],
            primary_case_id="case_1",
            decision_text="Aangenomen.",
            display_name="Stemming",
        ),
        _node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "stemming_2",
            ["TK"],
            source="tk",
            date="2025-03-09",
            passed=False,
            dossier_numbers=["36001", "36000"],
        ),
        _node(
            COLLECTION_DECISIONS,
            NodeType.DECISION,
            "stemming_3",
            ["TK"],
            source="tk",
            date="2025-03-10",
            passed=True,
            dossier_numbers=["36001"],
        ),
        _node(
            COLLECTION_COMMITMENTS,
            NodeType.COMMITMENT,
            "toez_1",
            ["TK"],
            source="tk",
            made_on="2025-03-11",
            text="De minister zegt toe.",
            minister_name="Minister X",
            status="Openstaand",
            display_name="Toezegging",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "bwbr0001",
            ["BWB"],
            bwb_id="BWBR0001",
            display_name="Wegenwet",
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0001_5",
            ["BWB", "Article"],
            bwb_id="BWBR0001",
            article_number="5",
            text=LONG_TEXT,
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0001_6",
            ["BWB", "Article"],
            bwb_id="BWBR0001",
            article_number="6",
        ),
        _node(
            COLLECTION_ARTICLE_VERSIONS,
            NodeType.ARTICLE_VERSION,
            "bwbr0001_av_5_1",
            ["BWB", "ArticleVersion"],
            bwb_id="BWBR0001",
            article_number="5",
        ),
        _node(
            COLLECTION_ARTICLE_VERSIONS,
            NodeType.ARTICLE_VERSION,
            "bwbr0001_av_5_2",
            ["BWB", "ArticleVersion"],
            bwb_id="BWBR0001",
            article_number="5",
        ),
        _node(  # a version nobody made an article of
            COLLECTION_ARTICLE_VERSIONS,
            NodeType.ARTICLE_VERSION,
            "orphan_av",
            ["BWB", "ArticleVersion"],
            bwb_id="BWBR0001",
            article_number="9",
        ),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)

    d = COLLECTION_DOCUMENTS
    edges = EdgeWriter(store, what=None)
    for from_id, to_id, relation in [
        (f"{d}/mvt", DOSSIER, RELATION_PART_OF),
        (f"{d}/motie", f"{COLLECTION_CASES}/case_1", RELATION_PART_OF),
        (f"{COLLECTION_CASES}/case_1", DOSSIER, RELATION_PART_OF),
        (f"{d}/ek_1", DOSSIER, RELATION_PART_OF),
        (f"{d}/other", f"{COLLECTION_DOSSIERS}/36001", RELATION_PART_OF),
        (f"{COLLECTION_ACTIVITIES}/act_committee", DOSSIER, RELATION_ABOUT),
        (f"{COLLECTION_ACTIVITIES}/act_plenary", DOSSIER, RELATION_ABOUT),
        (
            f"{COLLECTION_ACTIVITIES}/act_committee",
            f"{COLLECTION_COMMITTEES}/c1",
            RELATION_LED_BY,
        ),
        (f"{COLLECTION_DECISIONS}/stemming_1", DOSSIER, RELATION_ABOUT),
        (f"{COLLECTION_COMMITMENTS}/toez_1", DOSSIER, RELATION_ABOUT),
        # what the memorandum explains: two versions of one article, one article
        # once more directly, another article, the law, and a version without article
        (
            f"{d}/mvt",
            f"{COLLECTION_ARTICLE_VERSIONS}/bwbr0001_av_5_1",
            RELATION_EXPLAINS,
        ),
        (
            f"{d}/mvt",
            f"{COLLECTION_ARTICLE_VERSIONS}/bwbr0001_av_5_2",
            RELATION_EXPLAINS,
        ),
        (f"{d}/mvt", f"{COLLECTION_ARTICLES}/bwbr0001_5", RELATION_EXPLAINS),
        (f"{d}/mvt", f"{COLLECTION_ARTICLES}/bwbr0001_6", RELATION_EXPLAINS),
        (f"{d}/mvt", f"{COLLECTION_INSTRUMENTS}/bwbr0001", RELATION_EXPLAINS),
        (f"{d}/mvt", f"{COLLECTION_ARTICLE_VERSIONS}/orphan_av", RELATION_EXPLAINS),
        (
            f"{COLLECTION_ARTICLE_VERSIONS}/bwbr0001_av_5_1",
            f"{COLLECTION_ARTICLES}/bwbr0001_5",
            RELATION_VERSION_OF,
        ),
        (
            f"{COLLECTION_ARTICLE_VERSIONS}/bwbr0001_av_5_2",
            f"{COLLECTION_ARTICLES}/bwbr0001_5",
            RELATION_VERSION_OF,
        ),
    ]:
        edges.add(from_id, to_id, relation, source="test")
    edges.flush()


def _keys(page: dict[str, Any]) -> list[str]:
    return [row["key"] for row in page["items"]]


def test_the_documents_of_a_dossier_are_direct_and_through_a_case(
    store: ArangoStore,
) -> None:
    _build(store)

    page = get_dossier_documents(store, DOSSIER, limit=2, offset=0)
    assert page["total"] == 3  # the memorandum, the motion via its case, the EK paper
    assert _keys(page) == ["ek_1", "motie"]  # newest first, two of three
    rest = get_dossier_documents(store, DOSSIER, limit=2, offset=2)
    assert _keys(rest) == ["mvt"] and rest["total"] == 3
    assert get_dossier_documents(store, f"{COLLECTION_DOSSIERS}/36001")["total"] == 1


def test_the_timeline_carries_slim_bodies_and_the_committee_of_an_activity(
    store: ArangoStore,
) -> None:
    _build(store)

    rows = get_dossier_timeline(store, DOSSIER, order="asc", limit=50)
    entries = {row["node_id"].split("/")[1]: timeline_entry(row) for row in rows}
    # the motion is PART_OF a case only: it is on the timeline as the document of its decision
    assert list(entries) == [
        "mvt",
        "ek_1",
        "act_committee",
        "act_plenary",
        "stemming_1",
        "toez_1",
    ]

    for name, entry in entries.items():  # no document text, no payload
        dumped = entry.model_dump_json()
        assert '"raw"' not in dumped and len(dumped) < 2000, name
        assert ("wordt gewijzigd" in dumped) == (name == "stemming_1"), (
            name
        )  # its excerpt

    mvt = entries["mvt"].model_dump()
    assert mvt["node_type"] == "document"
    assert mvt["body"] == {
        "chamber": "TK",
        "source": "tk",
        "is_explanatory": True,
        "kind": "Memorie van toelichting",
        "title": "Memorie van toelichting mvt",
        "sequence": 3,
        "number": "3",
        # the dossier its sequence is a number of: this seed stores none
        "dossier_number": None,
        "session_year": "2024-2025",
        # made from the document number, never stored
        "tk_url": "https://www.tweedekamer.nl/kamerstukken/detail"
        "?id=2025D00003&did=2025D00003",
        "url": None,
    }
    ek = entries["ek_1"].model_dump()["body"]
    assert ek["chamber"] == "EK" and ek["url"] == "https://ek.example/1"
    # the letter of an Eerste Kamer paper, which has no sequence: Kamerstukken I, 36000, C
    assert ek["number"] == "C" and ek["sequence"] is None
    assert ek["is_explanatory"] is False

    committee = entries["act_committee"].model_dump()
    assert committee["committee"] == {
        "key": "c1",
        "slug": "ienw",
        "name": "Vaste commissie voor Infrastructuur",
    }
    assert committee["body"] == {
        "kind": "Commissiedebat",
        "agenda_title": "2025-03-06 - Debat",
        "number": "2025A1",
        "status": None,
    }
    assert entries["act_plenary"].committee is None  # type: ignore[union-attr]

    decision = entries["stemming_1"].model_dump()["body"]
    assert decision["tally"] == {"Voor": 80, "Tegen": 70}
    assert decision["passed"] is True and decision["external_id"] == "b1"
    document = decision["document"]
    assert document["key"] == "motie" and document["chamber"] == "TK"
    assert document["dictum_excerpt"].startswith("Artikel 5 wordt gewijzigd.")
    assert len(document["dictum_excerpt"]) <= 280
    assert [s["role"] for s in document["signatories"]] == ["indiener", "mede-indiener"]

    commitment = entries["toez_1"].model_dump()["body"]
    assert commitment["minister_name"] == "Minister X"
    assert commitment["status"] == "Openstaand"


def test_only_an_activity_entry_has_a_committee(store: ArangoStore) -> None:
    _build(store)

    rows = get_dossier_timeline(store, DOSSIER, order="asc", limit=2)
    assert [row["node_type"] for row in rows] == ["document"] * 2
    assert all(row["committee"] is None for row in rows)
    kind_filtered = get_dossier_timeline(
        store, DOSSIER, kind_filter=["commissiedebat"], limit=10
    )
    assert [row["committee"]["slug"] for row in kind_filtered] == ["ienw"]


# ── hub ──


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
    # a title of its own: a dossier without one takes it from ``normalize tk``'s signals
    dossier = g.node(
        "dossiers", "36001", number="36001", label="36001", closed=False, title="Wet A"
    )
    other = g.node("dossiers", "36002", number="36002", label="36002", closed=False)
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
    store: ArangoStore,
) -> None:
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


def test_a_dossier_without_links_has_an_empty_hub(store: ArangoStore) -> None:
    g = Graph(store)
    g.node("dossiers", "36003", number="36003", label="36003")
    g.write()

    hub = get_dossier_hub(store, "dossiers/36003")

    assert hub == {
        "instruments": [],
        "committees": [],
        "documents_by_kind": {},
        "senate": {"document_count": 0, "first_date": None},
    }


def test_the_hub_of_a_big_amending_law_walks_indexes_and_stays_fast(
    store: ArangoStore,
) -> None:
    """One publication that amends 3,000 articles of 300 laws, and 600 documents."""
    g = Graph(store)
    dossier = g.node("dossiers", "36004", number="36004", label="36004")
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

    # the edges are read by their ends, never whole (every document here is the
    # dossier's, so its table may be read whole)
    store.execute("ANALYZE")
    from lawgraph.db.queries import dossiers

    (plan,) = store.execute(
        f"EXPLAIN (FORMAT JSON) {dossiers._DOSSIER_HUB_SQL}",
        {
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
    scans = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("Node Type") == "Seq Scan":
            scans.append(node["Relation Name"])
        for child in node.get("Plans", []):
            walk(child)

    walk(plan[0]["Plan"])
    assert "edges" not in scans, scans


def test_the_routes_answer_from_the_real_graph(store: ArangoStore) -> None:
    _hub_graph(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        hub = client.get("/api/dossiers/36001").json()
        assert hub["number"] == "36001" and hub["documents_by_kind"]["Amendement"] == 1
        assert hub["instruments"][0]["relation"] == "legislated_in"
        assert [c["slug"] for c in hub["committees"]] == ["a", "b"]
        assert hub["senate"]["first_date"] == "2024-04-01"
    finally:
        app.dependency_overrides.pop(get_store, None)


# ── list ──

TITLE = (
    "Wijziging van de Uitvoeringswet Algemene verordening gegevensbescherming "
    "(Verzamelwet gegevensbescherming)"
)


def _dossier(number: str, suffix: str, **props: Any) -> Node:
    label = f"{number}-{suffix}" if suffix else number
    return Node(
        collection=COLLECTION_DOSSIERS,
        type=NodeType.DOSSIER,
        key=label.lower().replace("-", "_"),
        labels=["TK"],
        props={
            "number": number,
            "suffix": suffix,
            "label": label,
            "order": dossier_order(number, suffix),
            **props,
        },
    )


DOSSIERS = [
    _dossier(
        "36264",
        "",
        title=TITLE,
        kind="Wetgeving",
        opened_on="2023-01-10",
        closed=True,
        closed_on="2026-06-26",
        outcome="aangenomen",
    ),
    _dossier("37020", "", title="Miljoenennota", kind=None, opened_on="2026-09-15"),
    _dossier(
        "37020",
        "XV",
        title="Begroting SZW",
        kind="Begroting",
        opened_on="2026-09-15",
    ),
    _dossier(
        "37020",
        "IIA",
        title="Begroting Staten-Generaal",
        kind="Begroting",
        opened_on="2026-09-15",
    ),
    _dossier(
        "35000",
        "",
        title="Verworpen wet",
        kind="Wetgeving",
        opened_on="2018-01-01",
        closed=True,
        closed_on="2019-01-01",
        outcome="verworpen",
    ),
]


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_dossier_can_be_listed_found_and_ordered(store: ArangoStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(DOSSIERS)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        everything = _get(client, "/api/dossiers")
        found = _get(client, "/api/dossiers", subject="verzamelwet gegevensbescherming")
        closed = _get(client, "/api/dossiers", status="closed", sort="closed_on")
        enacted = _get(client, "/api/dossiers", outcome="aangenomen")
        budget = _get(client, "/api/dossiers", number="37020")
        by_title = _get(client, "/api/dossiers", sort="title", limit=2)
        still_open = _get(client, "/api/dossiers", status="open")
        bad = client.get("/api/dossiers", params={"has_phase": "nope"}).status_code
        budgets = _get(client, "/api/dossiers", kind="Begroting")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert everything["total"] == 5
    assert {f["value"]: f["count"] for f in everything["facets"]["status"]} == {
        "open": 3,
        "closed": 2,
    }
    assert [d["number"] for d in found["items"]] == ["36264"]
    assert found["items"][0]["short_title"] == "Verzamelwet gegevensbescherming"
    assert found["items"][0]["outcome"] == "aangenomen"
    assert [d["number"] for d in closed["items"]] == ["36264", "35000"]
    # the facet of a chosen dimension keeps its other values
    assert {f["value"]: f["count"] for f in closed["facets"]["status"]} == {
        "open": 3,
        "closed": 2,
    }
    assert [d["number"] for d in enacted["items"]] == ["36264"]
    # a number: that number and its chapters, in the order of the Kamer
    assert [d["number"] for d in budget["items"]] == ["37020", "37020-IIA", "37020-XV"]
    assert [d["title"] for d in by_title["items"]] == [
        "Begroting Staten-Generaal",
        "Begroting SZW",
    ]
    assert by_title["total"] == 5
    assert still_open["total"] == 3
    assert bad == 422
    assert budgets["total"] == 2
    assert {f["value"]: f["count"] for f in budgets["facets"]["kind"]} == {
        "Begroting": 2,
        "Wetgeving": 2,
        None: 1,
    }


# ── laws ──

LAWS_TITLE = (
    "Wijziging van het Wetboek van Strafrecht en het Wetboek van Strafvordering in "
    "verband met de modernisering van de strafrechtelijke aanpak"
)
LAW = f"{COLLECTION_INSTRUMENTS}/bwbr0001854"


def _bare(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(collection=collection, type=node_type, key=key, labels=[], props=props)


def _laws_seed(store: ArangoStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _bare(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "34372",
                    number="34372",
                    label="34372",
                    title=LAWS_TITLE,
                ),
                _bare(
                    COLLECTION_INSTRUMENTS,
                    NodeType.INSTRUMENT,
                    "bwbr0001854",
                    bwb_id="BWBR0001854",
                    citation_title="Wetboek van Strafrecht",
                    display_name="Wetboek van Strafrecht",
                    jurisdiction="nl",
                ),
                _bare(
                    COLLECTION_ARTICLES,
                    NodeType.ARTICLE,
                    "bwbr0001854_41",
                    bwb_id="BWBR0001854",
                    article_number="41",
                ),
                _bare(
                    COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "bill", kind="Wetsvoorstel"
                ),
            ]
        )
    article = f"{COLLECTION_ARTICLES}/bwbr0001854_41"
    bill = f"{COLLECTION_DOCUMENTS}/bill"
    with EdgeWriter(store, what=None) as edges:
        edges.add(article, LAW, RELATION_PART_OF, source="t")
        edges.add(bill, f"{COLLECTION_DOSSIERS}/34372", RELATION_PART_OF, source="t")
        edges.add(bill, article, RELATION_AMENDS, source="t")
        edges.add(bill, LAW, RELATION_INTRODUCES, source="t")
        edges.add(bill, LAW, RELATION_AMENDS, source="t", status="voorgesteld")


def test_a_law_is_one_item_and_the_laws_of_the_title_are_named(
    store: ArangoStore,
) -> None:
    _laws_seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get("/api/dossiers/34372")
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    dossier = response.json()

    (law,) = dossier["instruments"]
    assert (law["bwb_id"], law["relation"], law["status"]) == (
        "BWBR0001854",
        "amends",
        "canoniek",
    )
    assert law["links"] == [
        {"relation": "amends", "status": "canoniek"},
        {"relation": "introduces", "status": "canoniek"},
        {"relation": "amends", "status": "voorgesteld"},
    ]
    assert dossier["laws_named"] == [
        {
            "name": "Wetboek van Strafrecht",
            "loaded": True,
            "key": "bwbr0001854",
            "bwb_id": "BWBR0001854",
        },
        {
            "name": "Wetboek van Strafvordering",
            "loaded": False,
            "key": None,
            "bwb_id": None,
        },
    ]


# ── what the moved tests do not pin: order, ties, nulls, shapes ──────────────


def _doc(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict:
    return {"_key": key, "type": node_type, "labels": labels or [], "props": props}


def _link(key: str, source: str, target: str, relation: str, **rest: Any) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        **rest,
    }


def _write(
    store: ArangoStore,
    nodes: dict[str, list[dict[str, Any]]],
    edges: list[dict[str, Any]] | None = None,
) -> None:
    for collection, docs in nodes.items():
        store.bulk_insert_or_update_nodes(collection, docs)
    if edges:
        store.bulk_insert_or_update_edges(edges)


TIMELINE = f"{COLLECTION_DOSSIERS}/40000"


def _timeline_graph(store: ArangoStore) -> None:
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc("40000", "dossier", number="40000", closed_on="2025-02-01")
            ],
            COLLECTION_DOCUMENTS: [
                _doc("d_b", "document", ["TK"], date="2025-01-01"),
                _doc("d_a", "document", ["TK"], date="2025-01-01", kind="Brief"),
                _doc("undated", "document", ["TK"], date=None),
            ],
            COLLECTION_ACTIVITIES: [
                _doc(
                    "planned", "activity", ["TK"], date="2025-02-15", status="Gepland"
                ),
                _doc("held", "activity", ["TK"], status="Uitgevoerd"),
            ],
            COLLECTION_DECISIONS: [
                # the day it closed, with a time: not after the closing
                _doc(
                    "vote",
                    "decision",
                    ["TK"],
                    date="2025-02-01T10:00:00",
                    passed=True,
                    subject="Motie",
                    decision_id="b1",
                )
            ],
            COLLECTION_COMMITMENTS: [
                _doc(
                    "promise",
                    "commitment",
                    ["TK"],
                    made_on="2025-03-01",
                    status="Openstaand",
                    text="Zegt toe",
                    minister_name="X",
                    other="left out",
                )
            ],
            COLLECTION_COMMITTEES: [
                _doc("c_b", "committee", name="B", slug="b"),
                _doc("c_a", "committee", name="A", slug="a"),
            ],
        },
        [
            _link("t1", f"{COLLECTION_DOCUMENTS}/d_b", TIMELINE, RELATION_PART_OF),
            _link("t2", f"{COLLECTION_DOCUMENTS}/d_a", TIMELINE, RELATION_PART_OF),
            _link("t3", f"{COLLECTION_DOCUMENTS}/undated", TIMELINE, RELATION_PART_OF),
            _link("t4", f"{COLLECTION_ACTIVITIES}/planned", TIMELINE, RELATION_ABOUT),
            _link("t5", f"{COLLECTION_ACTIVITIES}/held", TIMELINE, RELATION_ABOUT),
            _link("t6", f"{COLLECTION_DECISIONS}/vote", TIMELINE, RELATION_ABOUT),
            _link("t7", f"{COLLECTION_COMMITMENTS}/promise", TIMELINE, RELATION_ABOUT),
            # the first committee by id leads it; a gone one does not count
            _link(
                "l1",
                f"{COLLECTION_ACTIVITIES}/planned",
                f"{COLLECTION_COMMITTEES}/c_b",
                RELATION_LED_BY,
            ),
            _link(
                "l2",
                f"{COLLECTION_ACTIVITIES}/planned",
                f"{COLLECTION_COMMITTEES}/c_a",
                RELATION_LED_BY,
            ),
            _link(
                "l3",
                f"{COLLECTION_ACTIVITIES}/planned",
                f"{COLLECTION_COMMITTEES}/c_0",
                RELATION_LED_BY,
            ),
        ],
    )


def test_the_timeline_sorts_by_date_then_id_and_drops_rows_without_a_date(
    store: ArangoStore,
) -> None:
    _timeline_graph(store)

    newest = get_dossier_timeline(store, TIMELINE)
    oldest = get_dossier_timeline(store, TIMELINE, order="asc")
    unplanned = get_dossier_timeline(store, TIMELINE, include_planned=False)
    two = get_dossier_timeline(store, TIMELINE, order="asc", limit=2)
    kinds = get_dossier_timeline(store, TIMELINE, kind_filter=["BRIEF", "document"])

    ids = [row["node_id"].split("/")[1] for row in newest]
    assert ids == ["promise", "planned", "vote", "d_b", "d_a"]
    assert [row["node_id"].split("/")[1] for row in oldest] == ids[::-1]
    assert [row["node_id"].split("/")[1] for row in unplanned] == [
        "promise",
        "vote",
        "d_b",
        "d_a",
    ]
    assert [row["node_id"].split("/")[1] for row in two] == ["d_a", "d_b"]
    assert [row["node_id"].split("/")[1] for row in kinds] == ["d_b", "d_a"]

    by_id = {row["node_id"].split("/")[1]: row for row in newest}
    # a kind of its own, else the kind of its node type
    assert [by_id[k]["kind"] for k in ids] == [
        "Toezegging",
        "Activiteit",
        "Stemming",
        "Document",
        "Brief",
    ]
    assert [by_id[k]["after_closure"] for k in ids] == [True, True, False, False, False]
    assert [by_id[k]["planned"] for k in ids] == [False, True, False, False, False]
    assert by_id["promise"]["date"] == "2025-03-01"  # made_on stands in for a date
    assert by_id["planned"]["committee"] == {"key": "c_a", "slug": "a", "name": "A"}
    assert by_id["promise"]["committee"] is None
    # KEEP: the props it shows in byte order, whatever order they are stored in
    assert list(by_id["promise"]["body"]) == ["minister_name", "status", "text"]


def test_a_timeline_row_has_the_keys_of_its_merge(store: ArangoStore) -> None:
    _timeline_graph(store)

    (row,) = get_dossier_timeline(store, TIMELINE, limit=1)

    # MERGE: the entry's keys in byte order, then the two it adds as ArangoDB did
    assert list(row) == [
        "body",
        "date",
        "kind",
        "labels",
        "node_id",
        "node_type",
        "planned",
        "title",
        "after_closure",
        "committee",
    ]
    assert row["labels"] == ["TK"] and row["title"] is None


def test_an_empty_dossier_has_an_empty_timeline_and_no_documents(
    store: ArangoStore,
) -> None:
    _write(store, {COLLECTION_DOSSIERS: [_doc("40001", "dossier")]})
    dossier = f"{COLLECTION_DOSSIERS}/40001"

    assert get_dossier_timeline(store, dossier) == []
    assert get_dossier_documents(store, dossier) == {"total": 0, "items": []}
    assert count_dossier_members(store, dossier) == {
        "documents": 0,
        "activities": 0,
        "decisions": 0,
        "commitments": 0,
    }


def test_the_documents_of_a_dossier_page_newest_first_and_by_key(
    store: ArangoStore,
) -> None:
    dossier = f"{COLLECTION_DOSSIERS}/40002"
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [_doc("40002", "dossier")],
            COLLECTION_CASES: [_doc("case", "case")],
            COLLECTION_DOCUMENTS: [
                _doc(
                    "b",
                    "document",
                    ["TK"],
                    date="2025-01-01",
                    title=None,
                    display_name="Bee",
                ),
                _doc(
                    "a", "document", ["EK"], date="2025-01-01", title="Aa", sequence=2
                ),
                _doc("none", "document", ["TK"], date=None),
                _doc("new", "document", ["TK"], date="2025-06-01"),
            ],
        },
        [
            _link("p1", f"{COLLECTION_DOCUMENTS}/b", dossier, RELATION_PART_OF),
            _link("p2", f"{COLLECTION_DOCUMENTS}/a", dossier, RELATION_PART_OF),
            _link("p3", f"{COLLECTION_DOCUMENTS}/none", dossier, RELATION_PART_OF),
            _link(
                "p4",
                f"{COLLECTION_DOCUMENTS}/new",
                f"{COLLECTION_CASES}/case",
                RELATION_PART_OF,
            ),
            _link("p5", f"{COLLECTION_CASES}/case", dossier, RELATION_PART_OF),
            # through the case as well: once
            _link(
                "p6",
                f"{COLLECTION_DOCUMENTS}/a",
                f"{COLLECTION_CASES}/case",
                RELATION_PART_OF,
            ),
        ],
    )

    first = get_dossier_documents(store, dossier, limit=3)
    rest = get_dossier_documents(store, dossier, limit=3, offset=3)
    past = get_dossier_documents(store, dossier, limit=3, offset=9)

    assert list(first) == ["total", "items"]
    assert first["total"] == 4 and isinstance(first["total"], int)
    assert [d["key"] for d in first["items"]] == ["new", "a", "b"]
    assert [d["key"] for d in rest["items"]] == ["none"]
    assert past == {"total": 4, "items": []}
    a, b = first["items"][1:]
    assert list(a) == [
        "id",
        "key",
        "kind",
        "title",
        "sequence",
        "dossier_number",
        "dossier_suffix",
        "session_year",
        "date",
        "document_number",
        "display_name",
        "source",
        "labels",
    ]
    assert (a["id"], a["title"], a["sequence"], a["labels"]) == (
        f"{COLLECTION_DOCUMENTS}/a",
        "Aa",
        2,
        ["EK"],
    )
    assert b["title"] == "Bee"  # no title: its display name


def test_the_hub_lists_its_parts_in_their_order(store: ArangoStore) -> None:
    dossier = f"{COLLECTION_DOSSIERS}/40003"
    law = f"{COLLECTION_INSTRUMENTS}/law"
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [_doc("40003", "dossier")],
            COLLECTION_INSTRUMENTS: [
                _doc("law", "instrument", bwb_id="BWBR1", display_name="Wet"),
                _doc("same_b", "instrument", display_name="Gelijk"),
                _doc("same_a", "instrument", display_name="Gelijk"),
                _doc("nameless", "instrument"),
            ],
            COLLECTION_DOCUMENTS: [
                _doc("m", "document", ["TK"], kind="motie", date="2024-01-01"),
                _doc("M", "document", ["TK"], kind="Motie", date="2024-01-02"),
                _doc("b", "document", ["EK"], kind="Brief", date=None),
                _doc("e", "document", ["EK"], kind="Brief", date="2024-03-01"),
            ],
        },
        [
            *(
                _link(
                    f"p_{k}", f"{COLLECTION_DOCUMENTS}/{k}", dossier, RELATION_PART_OF
                )
                for k in ("m", "M", "b", "e")
            ),
            *(
                _link(
                    f"l_{k}",
                    f"{COLLECTION_INSTRUMENTS}/{k}",
                    dossier,
                    RELATION_LEGISLATED_IN,
                )
                for k in ("law", "same_b", "same_a", "nameless")
            ),
            _link(
                "a1",
                f"{COLLECTION_DOCUMENTS}/m",
                law,
                RELATION_AMENDS,
                status=EDGE_STATUS_VOORGESTELD,
            ),
            _link("a2", f"{COLLECTION_DOCUMENTS}/M", law, RELATION_AMENDS),
            _link("a3", f"{COLLECTION_DOCUMENTS}/M", law, RELATION_AMENDS, status=None),
        ],
    )

    hub = get_dossier_hub(store, dossier)

    assert list(hub) == ["instruments", "committees", "documents_by_kind", "senate"]
    assert [(i["key"], i["relation"], i["status"]) for i in hub["instruments"]] == [
        ("nameless", "legislated_in", "canoniek"),  # no display name sorts first
        ("same_a", "legislated_in", "canoniek"),  # the key settles a tie
        ("same_b", "legislated_in", "canoniek"),
        ("law", "legislated_in", "canoniek"),
        ("law", "amends", "canoniek"),  # without a status: canonical, once
        ("law", "amends", "voorgesteld"),
    ]
    assert list(hub["instruments"][0]) == [
        "id",
        "key",
        "bwb_id",
        "celex",
        "display_name",
        "jurisdiction",
        "relation",
        "status",
    ]
    assert hub["committees"] == []
    # the kinds in the order of the collation, upper case first
    assert list(hub["documents_by_kind"].items()) == [
        ("Brief", 2),
        ("Motie", 1),
        ("motie", 1),
    ]
    assert hub["senate"] == {"document_count": 2, "first_date": "2024-03-01"}
    assert list(hub["senate"]) == ["document_count", "first_date"]


def test_the_mutations_are_the_edges_by_key_and_else_the_papers_that_name_it(
    store: ArangoStore,
) -> None:
    a1, a2 = f"{COLLECTION_ARTICLES}/a1", f"{COLLECTION_ARTICLES}/a2"
    member = f"{COLLECTION_DOCUMENTS}/member"
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc("41000", "dossier", label="41000"),
                _doc("41001", "dossier", label="41001"),
                _doc("41002", "dossier"),
            ],
            COLLECTION_DOCUMENTS: [
                _doc("member", "document"),
                _doc("fb_b", "document", dossier_numbers=["41001"]),
                _doc("fb_a", "document", dossier_numbers=["x", "41001"]),
                _doc("fb_s", "document", dossier_numbers="41001"),
            ],
            COLLECTION_ARTICLES: [_doc("a1", "article"), _doc("a2", "article")],
        },
        [
            _link("m0", member, f"{COLLECTION_DOSSIERS}/41000", RELATION_PART_OF),
            _link("e2", member, a1, RELATION_AMENDS, status="canoniek"),
            _link("e1", member, a2, RELATION_EXPLAINS, meta={"z": 1, "a": 2}),
            _link("e3", member, a1, "OTHER", status=EDGE_STATUS_VOORGESTELD),
            _link("e0", member, f"{COLLECTION_INSTRUMENTS}/x", RELATION_AMENDS),
            _link("e4", member, f"{COLLECTION_ARTICLES}/gone", RELATION_REPEALS),
            _link("k1", f"{COLLECTION_DOCUMENTS}/fb_b", a1, RELATION_AMENDS),
            _link("k9", f"{COLLECTION_DOCUMENTS}/fb_a", a2, RELATION_EXPLAINS),
            _link("k0", f"{COLLECTION_DOCUMENTS}/fb_s", a1, RELATION_AMENDS),
        ],
    )

    direct = get_dossier_mutations(store, f"{COLLECTION_DOSSIERS}/41000")
    named = get_dossier_mutations(store, f"{COLLECTION_DOSSIERS}/41001")
    nothing = get_dossier_mutations(store, f"{COLLECTION_DOSSIERS}/41002")

    assert [(e["to_id"], e["relation"], e["kind"]) for e in direct["edges"]] == [
        (a2, RELATION_EXPLAINS, "explanation"),
        (a1, RELATION_AMENDS, "mutation"),
        (a1, "OTHER", "mutation"),
        (f"{COLLECTION_ARTICLES}/gone", RELATION_REPEALS, "mutation"),
    ]
    assert list(direct["edges"][0]) == [
        "from_id",
        "to_id",
        "relation",
        "status",
        "meta",
        "kind",
    ]
    assert direct["edges"][0]["meta"] == {"z": 1, "a": 2}
    assert [(n["_id"], n["_kind"]) for n in direct["nodes"]] == [
        (member, "mutation"),  # an explanation first, then a change
        (a2, "explanation"),
        (a1, "mutation"),
    ]
    assert list(direct["nodes"][0]) == [
        "_key",
        "_id",
        "type",
        "labels",
        "props",
        "_kind",
    ]
    assert [e["from_id"].split("/")[1] for e in named["edges"]] == ["fb_a", "fb_b"]
    assert [n["_key"] for n in named["nodes"]] == ["fb_a", "a2", "fb_b", "a1"]
    assert nothing == {"nodes": [], "edges": []}


def test_the_related_dossiers_by_relation_direction_and_number(
    store: ArangoStore,
) -> None:
    here = f"{COLLECTION_DOSSIERS}/50000"
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc("50000", "dossier", number="50000"),
                _doc("50002_ii", "dossier", number="50002", suffix="II"),
                _doc("50002_i", "dossier", number="50002", suffix="I"),
                _doc("50001", "dossier", number="50001"),
                _doc("50003", "dossier", number="50003"),
                _doc("49999", "dossier", number="49999"),
            ]
        },
        [
            _link(
                "r1",
                here,
                f"{COLLECTION_DOSSIERS}/50002_ii",
                RELATION_REVISES,
                meta={"b": 1, "a": 2},
            ),
            _link("r2", here, f"{COLLECTION_DOSSIERS}/50002_i", RELATION_REVISES),
            _link("r3", here, f"{COLLECTION_DOSSIERS}/50001", RELATION_RELATED_TO),
            _link("r4", f"{COLLECTION_DOSSIERS}/50003", here, RELATION_REVISES),
            _link("r5", f"{COLLECTION_DOSSIERS}/49999", here, RELATION_ACCOMPANIES),
            _link("r6", here, f"{COLLECTION_DOSSIERS}/gone", RELATION_REVISES),
            _link("r7", here, f"{COLLECTION_DOSSIERS}/50001", RELATION_PART_OF),
        ],
    )

    rows = get_dossier_relations(store, here)

    assert [(r["relation"], r["direction"], r["dossier"]["_key"]) for r in rows] == [
        (RELATION_REVISES, "outgoing", "50002_i"),
        (RELATION_REVISES, "outgoing", "50002_ii"),
        (RELATION_REVISES, "incoming", "50003"),
        (RELATION_ACCOMPANIES, "incoming", "49999"),
        (RELATION_RELATED_TO, "outgoing", "50001"),
    ]
    assert list(rows[1]) == ["relation", "direction", "meta", "dossier"]
    assert rows[1]["meta"] == {"b": 1, "a": 2}
    assert list(rows[1]["dossier"]) == ["_key", "_id", "type", "labels", "props"]


def _listed(store: ArangoStore) -> None:
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc(
                    "a1",
                    "dossier",
                    label="1",
                    order="1",
                    opened_on="2025-01-01",
                    kind="Wetgeving",
                    outcome="aangenomen",
                    closed=True,
                    ministry="fin",
                    title="Alpha",
                    phases=[{"name": "Verslag", "done": True}],
                    initiative=False,
                ),
                _doc(
                    "a2",
                    "dossier",
                    label="2",
                    order="2",
                    opened_on="2025-01-01",
                    kind="Wetgeving",
                    closed=False,
                    title="beta",
                    phases=[{"name": "Verslag", "done": 0}],
                    initiative="true",
                ),
                _doc(
                    "a3",
                    "dossier",
                    label="3",
                    order=None,
                    opened_on=None,
                    kind=None,
                    closed=False,
                    title="Gamma",
                    initiative=True,
                ),
                _doc(
                    "a4",
                    "dossier",
                    label="10",
                    order="10",
                    opened_on="2024-01-01",
                    kind="Begroting",
                    closed=True,
                    outcome=None,
                    title="delta",
                    closed_on="2024-06-01",
                ),
            ]
        },
    )


def _keys_of(page: dict[str, Any]) -> list[str]:
    return [d["_key"] for d in page["items"]]


def test_the_dossier_list_sorts_with_its_ties_and_nulls(store: ArangoStore) -> None:
    _listed(store)
    every = DossierFilters()

    assert _keys_of(get_dossiers(store, every)) == ["a1", "a2", "a4", "a3"]
    assert _keys_of(get_dossiers(store, every, sort="number")) == [
        "a3",  # no order sorts first
        "a1",
        "a4",  # "10" before "2": the order is text
        "a2",
    ]
    assert _keys_of(get_dossiers(store, every, sort="closed_on")) == [
        "a4",
        "a1",
        "a2",
        "a3",
    ]
    assert _keys_of(get_dossiers(store, every, sort="title")) == [
        "a1",
        "a2",
        "a4",
        "a3",
    ]
    page = get_dossiers(store, every, limit=2, offset=2)
    assert _keys_of(page) == ["a4", "a3"] and page["total"] == 4
    assert _keys_of(get_dossiers(store, every, limit=2, offset=10)) == []


def test_the_dossier_list_counts_each_facet_without_its_own_filter(
    store: ArangoStore,
) -> None:
    _listed(store)

    page = get_dossiers(store, DossierFilters(status="closed", kinds=("Wetgeving",)))

    assert list(page) == ["total", "items", "facets"]
    assert page["total"] == 1 and isinstance(page["total"], int)
    assert list(page["facets"]) == ["status", "outcome", "kind", "phase", "ministry"]
    assert list(page["facets"]["status"][0]) == ["value", "count"]
    # under the kind filter: a1 and a2; equal counts by value
    assert page["facets"]["status"] == [
        {"value": "closed", "count": 1},
        {"value": "open", "count": 1},
    ]
    # under the status filter: a1 and a4; null sorts first among equal counts
    assert page["facets"]["kind"] == [
        {"value": "Begroting", "count": 1},
        {"value": "Wetgeving", "count": 1},
    ]
    assert page["facets"]["outcome"] == [{"value": "aangenomen", "count": 1}]
    assert page["facets"]["phase"] == [{"value": None, "count": 1}]
    every = get_dossiers(store, DossierFilters())["facets"]
    assert every["kind"] == [
        {"value": "Wetgeving", "count": 2},
        {"value": None, "count": 1},
        {"value": "Begroting", "count": 1},
    ]
    assert every["ministry"] == [
        {"value": None, "count": 3},
        {"value": "fin", "count": 1},
    ]


def test_the_dossier_list_filters_as_arangodb_compares(store: ArangoStore) -> None:
    _listed(store)

    def keys(**filters: Any) -> list[str]:
        return sorted(_keys_of(get_dossiers(store, DossierFilters(**filters))))

    assert keys(has_phase=("Verslag",)) == ["a1"]  # done 0 is not done
    assert keys(opened_from="2025-01-01") == ["a1", "a2"]
    assert keys(opened_to="2024-06-01") == ["a3", "a4"]  # null is below every day
    assert keys(initiative=True) == ["a3"]  # "true" is not true
    assert keys(initiative=False) == ["a1"]
    assert keys(number="1") == ["a1", "a4"]  # a prefix of the label
    assert keys(subject="ALP") == ["a1"]
    assert keys(outcome="aangenomen") == ["a1"]
    assert keys(status="open") == ["a2", "a3"]


def test_a_subject_matches_the_title_in_any_case_and_a_number_its_dossiers(
    store: ArangoStore,
) -> None:
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc(
                    "x1", "dossier", number="36000", suffix="", title="Wet op de ÉCOLE"
                ),
                _doc("x2", "dossier", number="36000", suffix="vii", title=1.5),
                _doc("x3", "dossier", number=36000, suffix="VII"),
            ]
        },
    )

    def keys(subject: str) -> list[str]:
        return sorted(_keys_of(get_dossiers(store, DossierFilters(subject=subject))))

    assert keys("école") == ["x1"]
    assert keys("1.5") == ["x2"]  # a number of a title is its text
    assert keys("36000") == ["x1", "x2"]  # the number as text
    assert keys("36000-VII") == ["x2"]


def test_the_committee_filter_keeps_the_dossiers_of_its_activities(
    store: ArangoStore,
) -> None:
    _listed(store)
    _write(
        store,
        {
            COLLECTION_COMMITTEES: [_doc("c1", "committee", slug="fin")],
            COLLECTION_ACTIVITIES: [_doc("act", "activity")],
        },
        [
            _link(
                "led",
                f"{COLLECTION_ACTIVITIES}/act",
                f"{COLLECTION_COMMITTEES}/c1",
                RELATION_LED_BY,
            ),
            _link(
                "ab1",
                f"{COLLECTION_ACTIVITIES}/act",
                f"{COLLECTION_DOSSIERS}/a2",
                RELATION_ABOUT,
            ),
            _link(
                "ab2",
                f"{COLLECTION_ACTIVITIES}/act",
                f"{COLLECTION_DOSSIERS}/a4",
                RELATION_ABOUT,
            ),
        ],
    )

    page = get_dossiers(store, DossierFilters(committee_slug="fin"))
    nobody = get_dossiers(store, DossierFilters(committee_slug="nope"))

    assert _keys_of(page) == ["a2", "a4"] and page["total"] == 2
    assert nobody["total"] == 0 and nobody["items"] == []
    assert nobody["facets"]["status"] == []


def test_the_members_of_a_dossier_are_counted_per_collection(
    store: ArangoStore,
) -> None:
    dossier = f"{COLLECTION_DOSSIERS}/42000"
    _write(
        store,
        {COLLECTION_DOSSIERS: [_doc("42000", "dossier")]},
        [
            _link("c1", f"{COLLECTION_DOCUMENTS}/d1", dossier, RELATION_PART_OF),
            _link("c2", f"{COLLECTION_DOCUMENTS}/d1", dossier, RELATION_ABOUT),
            _link("c3", f"{COLLECTION_ACTIVITIES}/a1", dossier, RELATION_ABOUT),
            _link("c4", f"{COLLECTION_COMMITMENTS}/k1", dossier, RELATION_ABOUT),
            _link("c5", f"{COLLECTION_CASES}/z1", dossier, RELATION_PART_OF),
            _link("c6", f"{COLLECTION_DECISIONS}/s1", dossier, RELATION_REVISES),
        ],
    )

    counts = count_dossier_members(store, dossier)

    # an edge each, whether its node is there or not
    assert counts == {"documents": 2, "activities": 1, "decisions": 0, "commitments": 1}
    assert list(counts) == ["documents", "activities", "decisions", "commitments"]
    assert all(isinstance(v, int) for v in counts.values())


def test_a_dossier_is_found_by_its_number(store: ArangoStore) -> None:
    _write(
        store,
        {COLLECTION_DOSSIERS: [_doc("37020_xv", "dossier", ["TK"], label="37020-XV")]},
    )

    found = get_dossier_by_number(store, "37020-XV")

    assert found is not None and found["_id"] == f"{COLLECTION_DOSSIERS}/37020_xv"
    assert found["props"] == {"label": "37020-XV"}
    assert get_dossier_by_number(store, "37021") is None


def test_the_laws_of_a_title_by_their_name_or_the_one_they_begin(
    store: ArangoStore,
) -> None:
    _write(
        store,
        {
            COLLECTION_INSTRUMENTS: [
                _doc("i_b", "instrument", citation_title="Wet A", bwb_id="BWBR2"),
                _doc("i_a", "instrument", title="wet a", bwb_id="BWBR1"),
                _doc("i_s", "instrument", short_title="WÉT S"),
                _doc("i_c", "instrument", citation_title="Wet C drie"),
                _doc("i_d", "instrument", citation_title="Wet B een"),
                _doc("i_e", "instrument", citation_title="Wet B twee"),
                _doc("i_x", "instrument", citation_title="Wet X", stub=True),
                _doc("i_y", "instrument", citation_title="Wet Y", stub="true"),
            ]
        },
    )

    rows = get_laws_named(
        store, ["WET A", "Wet B", "Wet C", "wét s", "Wet X", "Wet Y", "WET A"]
    )

    assert [(r["name"], r["loaded"], r["key"], r["bwb_id"]) for r in rows] == [
        ("WET A", True, "i_a", "BWBR1"),  # the first by key of the exact ones
        ("Wet B", False, None, None),  # begins two
        ("Wet C", True, "i_c", None),  # begins one
        ("wét s", True, "i_s", None),
        ("Wet X", False, None, None),  # a stub is never one
        ("Wet Y", True, "i_y", None),  # "true" is not true
        ("WET A", True, "i_a", "BWBR1"),
    ]
    assert list(rows[0]) == ["name", "loaded", "key", "bwb_id"]
    assert get_laws_named(store, []) == []


def test_the_values_of_the_tweede_kamer_a_phase_can_name(store: ArangoStore) -> None:
    _write(
        store,
        {
            COLLECTION_DOCUMENTS: [
                _doc("d1", "document", kind="Motie"),
                _doc("d2", "document", kind="Motie"),
                _doc("d3", "document", kind=""),
                _doc("d4", "document"),
            ],
            COLLECTION_ACTIVITIES: [_doc("a1", "activity", kind="Plenair debat")],
            COLLECTION_DECISIONS: [_doc("s1", "decision", decision_kind="Stemmingen")],
        },
    )

    values = tk_values(store)

    assert values == {
        "documents": {"Motie"},
        "activities": {"Plenair debat"},
        "decisions": {"Stemmingen"},
    }
    assert list(values) == ["documents", "activities", "decisions"]


ROWS = 60


def test_walking_the_pages_of_the_dossiers_finds_every_row_once(
    store: ArangoStore,
) -> None:
    """60 dossiers that share the value every order sorts on (moved from
    ``tests/integration/test_stable_paging.py``; a title each, so the list does not read
    ``normalize tk``'s signals)."""
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc(
                    f"dossier_{i:03d}",
                    "dossier",
                    ["TK"],
                    label=str(37000 + ROWS),
                    opened_on="2026-09-22",
                    title="Wet",
                )
                for i in range(ROWS)
            ]
        },
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        for params in ({"status": "open"}, {}, {"sort": "title"}):
            seen: list[Any] = []
            for offset in range(0, ROWS, 7):
                body = _get(client, "/api/dossiers", **params, limit=7, offset=offset)
                seen += [row["key"] for row in body["items"]]
            assert len(seen) == ROWS and len(set(seen)) == ROWS, params
    finally:
        app.dependency_overrides.pop(get_store, None)


# ── the signals of a dossier (``normalize tk``), and the list and detail that read them ──


def test_the_signals_of_a_dossier_are_the_few_fields_used_not_whole_documents(
    store: ArangoStore,
) -> None:
    """Moved from ``tests/integration/test_queries_normalize_tk.py``: a whole document
    (its text, its payload) is never what comes back, only a few fields of each."""
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [_doc("36000", "dossier", number="36000")],
            COLLECTION_DOCUMENTS: [
                _doc(
                    "d1",
                    "document",
                    ["TK"],
                    kind="Voorstel van wet",
                    date="2026-01-02",
                    title="Wet X",
                    dossier_numbers=["36000"],
                    case_kinds=["Wetgeving"],
                    dossier_number="36000",
                    sequence=2,
                    text="x" * 10_000,
                    raw={"Id": "d1"},
                )
            ],
            COLLECTION_ACTIVITIES: [
                _doc(
                    "a1",
                    "activity",
                    kind="Plenair debat",
                    date="2026-02-03",
                    status="x",
                )
            ],
        },
        [
            make_edge_doc("documents/d1", "dossiers/36000", RELATION_PART_OF),
            make_edge_doc("activities/a1", "dossiers/36000", RELATION_ABOUT),
        ],
    )

    (row,) = normalize_tk.dossier_signals(store, ["dossiers/36000"])
    assert row["dossier_id"] == "dossiers/36000"
    assert row["case_kinds"] == ["Wetgeving"]
    assert row["docs"] == [
        {
            "date": "2026-01-02",
            "kind": "Voorstel van wet",
            "own": ["36000", None],
            "sequence": 2,
            "title": "Wet X",
        }
    ]
    assert row["activities"] == [
        {"kind": "Plenair debat", "date": "2026-02-03", "status": "x"}
    ]
    assert row["decisions"] == []


def test_the_signals_of_dossiers_in_their_order_with_their_case_kinds(
    store: ArangoStore,
) -> None:
    here = f"{COLLECTION_DOSSIERS}/43000"
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc(
                    "43000",
                    "dossier",
                    opened_on="2025-01-01",
                    case_kinds=["Wetgeving", ["Initiatief"], None],
                ),
                _doc("43001", "dossier", case_kinds="Begroting"),
            ],
            COLLECTION_CASES: [
                _doc("z1", "case", kind="Amendement"),
                _doc("z2", "case", kind=["Motie", "Diep"]),
            ],
            COLLECTION_DOCUMENTS: [
                # one dossier: its case kinds count, its titles in order of preference
                _doc(
                    "b",
                    "document",
                    date="2025-02-01",
                    dossier_numbers=["43000"],
                    case_kinds=["brief"],
                    dossier_title="Dossiertitel",
                    title="T",
                    dossier_number="43000",
                    dossier_suffix="A",
                    sequence=1,
                ),
                # two dossiers: its case kinds do not
                _doc(
                    "a",
                    "document",
                    date="2025-02-01",
                    dossier_numbers=["1", "2"],
                    case_kinds=["Verworpen"],
                    title=None,
                    display_name="Naam",
                ),
                _doc("n", "document", date=None, case_kinds=["x"]),
                _doc("v", "document", date="2024-01-01", dossier_numbers=["43000"]),
            ],
            COLLECTION_ACTIVITIES: [
                _doc("act2", "activity", date="2025-03-01", kind="Debat", other=1),
                _doc("act1", "activity", date="2025-03-01", kind="Debat"),
            ],
            COLLECTION_DECISIONS: [
                _doc(
                    "s1",
                    "decision",
                    date="2025-04-01",
                    passed=True,
                    decision_kind="Stemmingen",
                    primary_case_kind="Motie",
                    status="ignored",
                    voters={"x": 1},
                ),
            ],
        },
        [
            _link("s_b", f"{COLLECTION_DOCUMENTS}/b", here, RELATION_PART_OF),
            _link("s_a", f"{COLLECTION_DOCUMENTS}/a", here, RELATION_PART_OF),
            _link("s_n", f"{COLLECTION_DOCUMENTS}/n", here, RELATION_PART_OF),
            _link("s_z1", f"{COLLECTION_CASES}/z1", here, RELATION_PART_OF),
            _link("s_z2", f"{COLLECTION_CASES}/z2", here, RELATION_PART_OF),
            _link(
                "s_v",
                f"{COLLECTION_DOCUMENTS}/v",
                f"{COLLECTION_CASES}/z1",
                RELATION_PART_OF,
            ),
            # through its case as well: once among the docs
            _link(
                "s_b2",
                f"{COLLECTION_DOCUMENTS}/b",
                f"{COLLECTION_CASES}/z2",
                RELATION_PART_OF,
            ),
            _link("s_1", f"{COLLECTION_ACTIVITIES}/act2", here, RELATION_ABOUT),
            _link("s_2", f"{COLLECTION_ACTIVITIES}/act1", here, RELATION_ABOUT),
            _link("s_3", f"{COLLECTION_DECISIONS}/s1", here, RELATION_ABOUT),
        ],
    )

    rows = list(
        normalize_tk.dossier_signals(
            store, [f"{COLLECTION_DOSSIERS}/43001", here, f"{COLLECTION_DOSSIERS}/gone"]
        )
    )

    assert [r["dossier_id"] for r in rows] == [
        f"{COLLECTION_DOSSIERS}/43001",
        here,
        f"{COLLECTION_DOSSIERS}/gone",
    ]
    assert list(rows[1]) == [
        "dossier_id",
        "opened_on",
        "case_kinds",
        "docs",
        "activities",
        "decisions",
    ]
    other, mine, gone = rows
    assert other["case_kinds"] == ["Begroting"] and other["docs"] == []
    assert gone == {
        "dossier_id": f"{COLLECTION_DOSSIERS}/gone",
        "opened_on": None,
        "case_kinds": [],
        "docs": [],
        "activities": [],
        "decisions": [],
    }
    assert mine["opened_on"] == "2025-01-01"
    # flattened two levels, without null, each once, in the order of the collation
    assert mine["case_kinds"] == [
        "Amendement",
        "brief",
        "Diep",
        "Initiatief",
        "Motie",
        "Wetgeving",
    ]
    # by date (none first), then id; keys in byte order
    assert [list(d) for d in mine["docs"]][0] == [
        "date",
        "kind",
        "own",
        "sequence",
        "title",
    ]
    assert [(d["date"], d["title"]) for d in mine["docs"]] == [
        (None, None),
        ("2024-01-01", None),
        ("2025-02-01", "Naam"),
        ("2025-02-01", "Dossiertitel"),
    ]
    assert mine["docs"][3]["own"] == ["43000", "A"]
    assert mine["activities"] == [
        {"kind": "Debat", "date": "2025-03-01", "status": None},
        {"kind": "Debat", "date": "2025-03-01", "status": None},
    ]
    assert mine["decisions"] == [
        {
            "case_kind": "Motie",
            "date": "2025-04-01",
            "decision_kind": "Stemmingen",
            "decision_text": None,
            "kind": None,
            "passed": True,
        }
    ]
    assert list(mine["decisions"][0]) == [
        "case_kind",
        "date",
        "decision_kind",
        "decision_text",
        "kind",
        "passed",
    ]
    assert list(normalize_tk.dossier_signals(store, [])) == []


def test_a_dossier_without_a_title_takes_it_and_its_opening_from_its_papers(
    store: ArangoStore,
) -> None:
    dossier = f"{COLLECTION_DOSSIERS}/38000"
    _write(
        store,
        {
            COLLECTION_DOSSIERS: [
                _doc(
                    "38000",
                    "dossier",
                    ["TK"],
                    number="38000",
                    label="38000",
                    order=dossier_order("38000", ""),
                )
            ],
            COLLECTION_DOCUMENTS: [
                _doc(
                    "letter",
                    "document",
                    ["TK"],
                    kind="Brief regering",
                    title="Brief",
                    date="2025-12-01",
                ),
                _doc(
                    "bill",
                    "document",
                    ["TK"],
                    kind="Voorstel van wet",
                    title="Wet Y",
                    dossier_title="Wet over Y",
                    date="2026-01-15",
                    sequence=1,
                    dossier_number="38000",
                    dossier_numbers=["38000"],
                    text="x" * 10_000,
                ),
            ],
        },
        [
            _link("e1", f"{COLLECTION_DOCUMENTS}/letter", dossier, RELATION_PART_OF),
            _link("e2", f"{COLLECTION_DOCUMENTS}/bill", dossier, RELATION_PART_OF),
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        detail = _get(client, "/api/dossiers/38000")
        listed = _get(client, "/api/dossiers", number="38000")
    finally:
        app.dependency_overrides.pop(get_store, None)

    # the title of the bill (its dossier title first), the date of nr. 1 of its own
    assert (detail["title"], detail["title_source"]) == ("Wet over Y", "document")
    assert detail["opened_on"] == "2026-01-15"
    (item,) = listed["items"]
    assert (item["title"], item["opened_on"]) == ("Wet over Y", "2026-01-15")
