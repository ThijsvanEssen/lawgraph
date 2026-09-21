"""The document, decision and dossier-timeline queries, run for real on a small graph.

The graph is written by hand (a dossier with a Tweede Kamer memorandum, motion and amendment,
an Eerste Kamer paper, an activity led by a committee and one without), so that every path
of the AQL has a node to take: a document PART_OF the dossier directly and through a case,
an EXPLAINS edge to an article version, an article and an instrument.
"""

from __future__ import annotations

from typing import Any

from lawgraph.api.queries.decisions import get_decisions
from lawgraph.api.queries.documents import get_document_links, list_documents
from lawgraph.api.queries.dossiers import get_dossier_timeline
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
    RELATION_ABOUT,
    RELATION_EXPLAINS,
    RELATION_LED_BY,
    RELATION_PART_OF,
    RELATION_VERSION_OF,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter

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
        _node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "36000", ["TK"], number="36000"),
        _node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "36001", ["TK"], number="36001"),
        _node(COLLECTION_CASES, NodeType.CASE, "case_1", ["TK"], number="2025Z1"),
        # a memorandum PART_OF the dossier itself
        _document(
            "mvt",
            "Memorie van toelichting",
            "2025-01-10",
            sequence=3,
            session_year="2024-2025",
            tk_url="https://tk.example/mvt",
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
            status="open",
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


def test_the_document_index_counts_its_matches_and_pages(database: str) -> None:
    store = ArangoStore()
    _build(store)
    everything = {"q": None, "kind": None, "chamber": None, "source": None}

    page = list_documents(store, **everything, dossier_id=None, limit=2, offset=0)
    assert page["total"] == 4 and len(page["items"]) == 2
    rest = list_documents(store, **everything, dossier_id=None, limit=2, offset=2)
    assert rest["total"] == 4
    assert sorted(_keys(page) + _keys(rest)) == ["ek_1", "motie", "mvt", "other"]

    ek = list_documents(
        store, **{**everything, "chamber": "ek"}, dossier_id=None, limit=1, offset=0
    )
    assert ek["total"] == 1 and _keys(ek) == ["ek_1"]
    assert ek["items"][0]["labels"] == ["EersteKamer", "EK"]
    assert ek["items"][0]["source"] == "eerstekamer"
    assert ek["items"][0]["has_text"] is False

    filtered = list_documents(
        store, **{**everything, "kind": "Motie"}, dossier_id=None, limit=10, offset=0
    )
    assert filtered["total"] == 1 and _keys(filtered) == ["motie"]
    assert list_documents(
        store, **{**everything, "q": "zzz"}, dossier_id=None, limit=10, offset=0
    ) == {"total": 0, "items": []}


def test_the_document_index_of_a_dossier_takes_direct_and_case_documents(
    database: str,
) -> None:
    store = ArangoStore()
    _build(store)
    everything = {"q": None, "kind": None, "chamber": None, "source": None}

    page = list_documents(store, **everything, dossier_id=DOSSIER, limit=2, offset=0)
    assert page["total"] == 3  # the memorandum, the motion via its case, the EK paper
    assert _keys(page) == ["ek_1", "motie"]  # newest first, two of three
    rest = list_documents(store, **everything, dossier_id=DOSSIER, limit=2, offset=2)
    assert _keys(rest) == ["mvt"] and rest["total"] == 3

    both = {**everything, "chamber": "EK"}
    only_ek = list_documents(store, **both, dossier_id=DOSSIER, limit=10, offset=0)
    assert only_ek["total"] == 1 and _keys(only_ek) == ["ek_1"]
    assert (
        list_documents(
            store,
            **everything,
            dossier_id=f"{COLLECTION_DOSSIERS}/36001",
            limit=10,
            offset=0,
        )["total"]
        == 1
    )


def test_a_document_links_to_its_dossiers_and_what_it_explains(
    database: str,
) -> None:
    store = ArangoStore()
    _build(store)

    links = get_document_links(store, f"{COLLECTION_DOCUMENTS}/mvt")
    assert links["dossier_numbers"] == ["36000"]
    assert links["explains"] == [
        {
            "id": f"{COLLECTION_ARTICLES}/bwbr0001_5",
            "key": "bwbr0001_5",
            "collection": "articles",
            "bwb_id": "BWBR0001",
            "article_number": "5",
        },
        {
            "id": f"{COLLECTION_ARTICLES}/bwbr0001_6",
            "key": "bwbr0001_6",
            "collection": "articles",
            "bwb_id": "BWBR0001",
            "article_number": "6",
        },
        {
            "id": f"{COLLECTION_INSTRUMENTS}/bwbr0001",
            "key": "bwbr0001",
            "collection": "instruments",
            "bwb_id": "BWBR0001",
            "article_number": None,
        },
    ]

    # an Eerste Kamer paper reaches its dossier through the same PART_OF edge
    ek = get_document_links(store, f"{COLLECTION_DOCUMENTS}/ek_1")
    assert ek == {"dossier_numbers": ["36000"], "explains": []}
    nothing = get_document_links(store, f"{COLLECTION_DOCUMENTS}/nowhere")
    assert nothing == {"dossier_numbers": [], "explains": []}


def test_the_decisions_of_a_dossier_are_read_from_an_index(database: str) -> None:
    store = ArangoStore()
    _build(store)

    page = get_decisions(store, dossier="36000", limit=10)
    assert page["total"] == 2
    assert [row["key"] for row in page["items"]] == ["stemming_2", "stemming_1"]
    assert get_decisions(store, dossier="36001", limit=1)["total"] == 2
    assert get_decisions(store, dossier="99999") == {"total": 0, "items": []}
    together = get_decisions(store, dossier="36000", passed=True)
    assert together["total"] == 1

    aql = (
        "FOR decision IN decisions FILTER @dossier IN decision.props.dossier_numbers "
        "SORT decision.props.date DESC LIMIT 0, 10 RETURN decision._key"
    )
    plan = store.db.aql.explain(aql, bind_vars={"dossier": "36000"})
    nodes = plan["nodes"]
    kinds = {node["type"] for node in nodes}
    assert "EnumerateCollectionNode" not in kinds, kinds
    index = next(node for node in nodes if node["type"] == "IndexNode")
    assert any(
        "dossier_numbers[*]" in ".".join(i["fields"]) for i in index["indexes"]
    ), index["indexes"]


def test_the_timeline_carries_slim_bodies_and_the_committee_of_an_activity(
    database: str,
) -> None:
    store = ArangoStore()
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
        "session_year": "2024-2025",
        "tk_url": "https://tk.example/mvt",
        "url": None,
    }
    ek = entries["ek_1"].model_dump()["body"]
    assert ek["chamber"] == "EK" and ek["url"] == "https://ek.example/1"
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
    assert commitment["status"] == "open"


def test_only_an_activity_entry_has_a_committee(database: str) -> None:
    store = ArangoStore()
    _build(store)

    rows = get_dossier_timeline(store, DOSSIER, order="asc", limit=2)
    assert [row["node_type"] for row in rows] == ["document"] * 2
    assert all(row["committee"] is None for row in rows)
    kind_filtered = get_dossier_timeline(
        store, DOSSIER, kind_filter=["commissiedebat"], limit=10
    )
    assert [row["committee"]["slug"] for row in kind_filtered] == ["ienw"]
