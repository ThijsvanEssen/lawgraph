"""The document queries on a real PostgreSQL: one document, its links (dossiers and what
it explains), the passages that explain an article and the list of the chambers' papers,
with its facets and through ``GET /api/documents``."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
    RELATION_PART_OF,
    RELATION_VERSION_OF,
)
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from lawgraph.db.queries.documents import (
    get_document,
    get_document_links,
    get_document_passages,
    list_documents,
)

DOSSIER = f"{COLLECTION_DOSSIERS}/36000"
D = COLLECTION_DOCUMENTS


def _node(
    collection: str, node_type: NodeType, key: str, labels: list[str], **props: Any
) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=labels, props=props
    )


def _document(key: str, kind: str, date: str, **props: Any) -> Node:
    return _node(
        D,
        NodeType.DOCUMENT,
        key,
        ["TK"],
        source="tk",
        kind=kind,
        title=f"{kind} {key}",
        display_name=f"{kind} {key}",
        date=date,
        **props,
    )


def _doc(key: str, labels: list[str], **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "document", "labels": labels, "props": props}


def _edge(
    key: str, source: str, target: str, relation: str, **meta: Any
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": None,
        "meta": meta,
    }


# ── one document ─────────────────────────────────────────────────────────────


def test_a_document_is_found_by_its_key_in_any_case(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(D, [_doc("abc", ["TK"], kind="Brief")])

    assert get_document(store, "ABC") == {
        "_key": "abc",
        "_id": f"{D}/abc",
        "type": "document",
        "labels": ["TK"],
        "props": {"kind": "Brief"},
    }
    assert get_document(store, "nope") is None


# ── links ────────────────────────────────────────────────────────────────────


def _build_links(store: GraphStore) -> None:
    """A dossier 36000 with a memorandum PART_OF it, a motion through its case, an Eerste
    Kamer paper; what the memorandum explains: two versions of one article, the article
    once more directly, another article, the law, and a version without an article."""
    article = {"bwb_id": "BWBR0001"}
    nodes = [
        _node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "36000", ["TK"], label="36000"),
        _node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "36001", ["TK"], label="36001"),
        _node(COLLECTION_CASES, NodeType.CASE, "case_1", ["TK"], number="2025Z1"),
        _document("mvt", "Memorie van toelichting", "2025-01-10"),
        _document("motie", "Motie", "2025-02-10"),
        _node(
            D,
            NodeType.DOCUMENT,
            "ek_1",
            ["EersteKamer", "EK"],
            kind="Nota",
            date="2025-03-01",
        ),
        _node(
            COLLECTION_INSTRUMENTS,
            NodeType.INSTRUMENT,
            "bwbr0001",
            ["BWB"],
            display_name="Wegenwet",
            **article,
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0001_5",
            ["BWB", "Article"],
            article_number="5",
            **article,
        ),
        _node(
            COLLECTION_ARTICLES,
            NodeType.ARTICLE,
            "bwbr0001_6",
            ["BWB", "Article"],
            article_number="6",
            **article,
        ),
        *(
            _node(
                COLLECTION_ARTICLE_VERSIONS,
                NodeType.ARTICLE_VERSION,
                key,
                ["BWB", "ArticleVersion"],
                article_number=number,
                **article,
            )
            for key, number in (
                ("bwbr0001_av_5_1", "5"),
                ("bwbr0001_av_5_2", "5"),
                ("orphan_av", "9"),
            )
        ),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)

    av = COLLECTION_ARTICLE_VERSIONS
    edges = EdgeWriter(store, what=None)
    for from_id, to_id, relation in [
        (f"{D}/mvt", DOSSIER, RELATION_PART_OF),
        (f"{D}/motie", f"{COLLECTION_CASES}/case_1", RELATION_PART_OF),
        (f"{COLLECTION_CASES}/case_1", DOSSIER, RELATION_PART_OF),
        (f"{D}/ek_1", DOSSIER, RELATION_PART_OF),
        (f"{D}/mvt", f"{av}/bwbr0001_av_5_1", RELATION_EXPLAINS),
        (f"{D}/mvt", f"{av}/bwbr0001_av_5_2", RELATION_EXPLAINS),
        (f"{D}/mvt", f"{COLLECTION_ARTICLES}/bwbr0001_5", RELATION_EXPLAINS),
        (f"{D}/mvt", f"{COLLECTION_ARTICLES}/bwbr0001_6", RELATION_EXPLAINS),
        (f"{D}/mvt", f"{COLLECTION_INSTRUMENTS}/bwbr0001", RELATION_EXPLAINS),
        (f"{D}/mvt", f"{av}/orphan_av", RELATION_EXPLAINS),
        (
            f"{av}/bwbr0001_av_5_1",
            f"{COLLECTION_ARTICLES}/bwbr0001_5",
            RELATION_VERSION_OF,
        ),
        (
            f"{av}/bwbr0001_av_5_2",
            f"{COLLECTION_ARTICLES}/bwbr0001_5",
            RELATION_VERSION_OF,
        ),
    ]:
        edges.add(from_id, to_id, relation, source="test")
    edges.flush()


def test_a_document_links_to_its_dossiers_and_what_it_explains(
    store: GraphStore,
) -> None:
    _build_links(store)

    links = get_document_links(store, f"{D}/mvt")
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
    # the keys in the order the AQL object listed them
    assert all(
        list(target) == ["id", "key", "collection", "bwb_id", "article_number"]
        for target in links["explains"]
    )
    assert list(links) == ["dossier_numbers", "explains"]

    # an Eerste Kamer paper reaches its dossier through the same PART_OF edge
    ek = get_document_links(store, f"{D}/ek_1")
    assert ek == {"dossier_numbers": ["36000"], "explains": []}
    # a motion is PART_OF its case, not of the dossier
    assert get_document_links(store, f"{D}/motie")["dossier_numbers"] == []
    nothing = get_document_links(store, f"{D}/nowhere")
    assert nothing == {"dossier_numbers": [], "explains": []}


def test_the_dossiers_of_a_document_are_sorted_once_each_and_need_a_label(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [
            {
                "_key": "b",
                "type": "dossier",
                "labels": [],
                "props": {"label": "37020-XV"},
            },
            {"_key": "a", "type": "dossier", "labels": [], "props": {"label": "36000"}},
            {"_key": "c", "type": "dossier", "labels": [], "props": {"label": "36000"}},
            {"_key": "nolabel", "type": "dossier", "labels": [], "props": {}},
            {
                "_key": "nulled",
                "type": "dossier",
                "labels": [],
                "props": {"label": None},
            },
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(f"p{n}", f"{D}/x", f"{COLLECTION_DOSSIERS}/{key}", RELATION_PART_OF)
            for n, key in enumerate(("b", "a", "c", "nolabel", "nulled", "missing"))
        ]
    )

    assert get_document_links(store, f"{D}/x")["dossier_numbers"] == [
        "36000",
        "37020-XV",
    ]


def test_a_version_resolves_to_the_first_article_by_id_even_when_it_is_gone(
    store: GraphStore,
) -> None:
    """``FIRST(... SORT v._to LIMIT 1 RETURN DOCUMENT(v._to))``: the first VERSION_OF
    target by id; when that article is not there the version is left out, though a later
    one is."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES,
        [
            {"_key": "b_2", "type": "article", "labels": [], "props": {"bwb_id": "B"}},
            {"_key": "c_1", "type": "article", "labels": [], "props": {}},
        ],
    )
    av = COLLECTION_ARTICLE_VERSIONS
    store.bulk_insert_or_update_edges(
        [
            _edge("e1", f"{D}/x", f"{av}/v1", RELATION_EXPLAINS),
            _edge("e2", f"{D}/x", f"{av}/v2", RELATION_EXPLAINS),
            # v1: two articles, the first by id is there
            _edge("v1c", f"{av}/v1", f"{COLLECTION_ARTICLES}/c_1", RELATION_VERSION_OF),
            _edge("v1b", f"{av}/v1", f"{COLLECTION_ARTICLES}/b_2", RELATION_VERSION_OF),
            # v2: the first by id is gone
            _edge("v2a", f"{av}/v2", f"{COLLECTION_ARTICLES}/a_0", RELATION_VERSION_OF),
            _edge("v2c", f"{av}/v2", f"{COLLECTION_ARTICLES}/c_1", RELATION_VERSION_OF),
            # an EXPLAINS edge to a node of another collection is no target
            _edge("e3", f"{D}/x", f"{COLLECTION_DOSSIERS}/d", RELATION_EXPLAINS),
        ]
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_DOSSIERS,
        [{"_key": "d", "type": "dossier", "labels": [], "props": {}}],
    )

    explains = get_document_links(store, f"{D}/x")["explains"]
    assert explains == [
        {
            "id": f"{COLLECTION_ARTICLES}/b_2",
            "key": "b_2",
            "collection": "articles",
            "bwb_id": "B",
            "article_number": None,
        }
    ]


# ── passages ─────────────────────────────────────────────────────────────────


def _passage(anchor: str, confidence: float, **more: Any) -> dict[str, Any]:
    return {
        "section_anchor": anchor,
        "heading": f"Artikel {anchor}",
        "char_start": 0,
        "char_end": 1,
        "match_type": "heading_target",
        "confidence": confidence,
        **more,
    }


def test_the_passages_of_an_article_come_from_it_and_its_versions_once_each(
    store: GraphStore,
) -> None:
    """The sections on the edges to the article and to its versions (the same stam_id),
    one row per section with its highest confidence; a version of another stam is not."""
    article_key = make_node_key("BWBR0009", "5")
    version = {"bwb_id": "BWBR0009", "article_number": "5"}
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _document("mvt_9", "Memorie van toelichting", "2025-01-10"),
                _node(
                    COLLECTION_ARTICLES,
                    NodeType.ARTICLE,
                    article_key,
                    ["BWB", "Article"],
                    stam_id="st1",
                    **version,
                ),
                _node(
                    COLLECTION_ARTICLE_VERSIONS,
                    NodeType.ARTICLE_VERSION,
                    "bwbr0009_av_st1",
                    ["BWB", "ArticleVersion"],
                    stam_id="st1",
                    **version,
                ),
                _node(
                    COLLECTION_ARTICLE_VERSIONS,
                    NodeType.ARTICLE_VERSION,
                    "bwbr0009_av_st2",
                    ["BWB", "ArticleVersion"],
                    stam_id="st2",
                    **version,
                ),
            ]
        )
    document = f"{D}/mvt_9"
    edges = EdgeWriter(store, what=None)
    for target, sections in [
        (f"{COLLECTION_ARTICLES}/{article_key}", [_passage("s-2", 0.7)]),
        (
            f"{COLLECTION_ARTICLE_VERSIONS}/bwbr0009_av_st1",
            [_passage("s-1", 0.9), _passage("s-2", 0.9)],
        ),
        (f"{COLLECTION_ARTICLE_VERSIONS}/bwbr0009_av_st2", [_passage("s-3", 1.0)]),
    ]:
        edges.add(
            document,
            target,
            RELATION_EXPLAINS,
            source="test",
            meta={"sections": sections},
        )
    edges.flush()

    rows = get_document_passages(store, document, "BWBR0009", "5")
    assert sorted((r["section_anchor"], r["confidence"]) for r in rows) == [
        ("s-1", 0.9),
        ("s-2", 0.9),
    ]
    assert get_document_passages(store, document, "BWBR0009", "6") == []


def test_of_equally_confident_sections_the_first_edge_by_key_wins(
    store: GraphStore,
) -> None:
    """Without a stam_id only the edges to the article itself count; sections that are
    not an array are skipped; the edges are read in key order."""
    article = make_node_key("BWBR0010", "1")
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES,
        [
            {
                "_key": article,
                "type": "article",
                "labels": [],
                "props": {"bwb_id": "BWBR0010", "article_number": "1"},
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLE_VERSIONS,
        [
            {
                "_key": "v",
                "type": "article_version",
                "labels": [],
                "props": {"bwb_id": "BWBR0010", "article_number": "1"},
            }
        ],
    )
    target = f"{COLLECTION_ARTICLES}/{article}"
    store.bulk_insert_or_update_edges(
        [
            _edge(
                "k2",
                f"{D}/m",
                target,
                RELATION_EXPLAINS,
                sections=[_passage("a", 0.5, edge="k2"), _passage("b", 0.4)],
            ),
            _edge(
                "k1",
                f"{D}/m",
                target,
                RELATION_EXPLAINS,
                sections=[_passage("a", 0.5, edge="k1")],
            ),
            _edge("k0", f"{D}/m", target, RELATION_EXPLAINS, sections="not a list"),
            _edge(
                "k3",
                f"{D}/m",
                f"{COLLECTION_ARTICLE_VERSIONS}/v",
                RELATION_EXPLAINS,
                sections=[_passage("c", 1.0)],
            ),
        ]
    )

    rows = get_document_passages(store, f"{D}/m", "BWBR0010", "1")
    assert [(r["section_anchor"], r.get("edge")) for r in rows] == [
        ("a", "k1"),
        ("b", None),
    ]
    assert get_document_passages(store, f"{D}/other", "BWBR0010", "1") == []


# ── the list ─────────────────────────────────────────────────────────────────


def _paper(key: str, labels: list[str], **props: Any) -> Node:
    return _node(D, NodeType.DOCUMENT, key, labels, **props)


PAPERS = [
    _paper(
        "mvt",
        ["TK", "Kamerstuk"],
        kind="Memorie van toelichting",
        title="Wet toekomstbestendige huurcommissie",
        date="2025-06-25",
        sequence=3,
        dossier_number="36791",
        dossier_numbers=["36791"],
        session_year="2024-2025",
    ),
    _paper(
        "motion",
        ["TK", "Kamerstuk"],
        kind="Motie",
        title="Motie over huur",
        date="2026-02-01",
        sequence=12,
        dossier_number="36791",
        dossier_numbers=["36791"],
        session_year="2025-2026",
    ),
    _paper(
        "ek_c",
        ["EersteKamer", "EK"],
        kind="Memorie van antwoord",
        title="Wet toekomstbestendige huurcommissie; Memorie van antwoord",
        date="2026-09-01",
        number="C",
        dossier_number="36791",
        dossier_numbers=["36791"],
        session_year="2025-2026",
    ),
    # neither chamber: a publication in the Staatsblad is no paper of a chamber
    _paper("stb", ["Staatsblad"], kind="Staatsblad", date="2026-09-20", title="Wet"),
    _paper(
        "other",
        ["TK", "Kamerstuk"],
        kind="Brief regering",
        title="Brief",
        date="2026-03-01",
        sequence=1,
        dossier_number="36000",
        dossier_numbers=["36000"],
    ),
]


def _get(client: TestClient, **params: Any) -> Any:
    response = client.get("/api/documents", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_papers_of_the_chambers_are_listed_counted_and_numbered(
    store: GraphStore,
) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(PAPERS)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        everything = _get(client)
        dossier = _get(client, dossier="36791")
        senate = _get(client, dossier="36791", chamber="EK")
        motions = _get(client, kind="Motie")
        window = _get(client, **{"from": "2026-01-01", "to": "2026-06-30"})
        page = _get(client, limit=1, facets="false")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert everything["total"] == 4  # not the Staatsblad
    assert [d["key"] for d in everything["items"]] == ["ek_c", "other", "motion", "mvt"]
    assert [d["key"] for d in dossier["items"]] == ["ek_c", "motion", "mvt"]
    ek = senate["items"][0]
    assert (ek["chamber"], ek["number"], ek["dossier_number"], ek["session_year"]) == (
        "EK",
        "C",
        "36791",
        "2025-2026",
    )
    mvt = dossier["items"][-1]
    assert (mvt["chamber"], mvt["number"]) == ("TK", "3")
    # each facet is counted without its own filter
    assert {f["value"]: f["count"] for f in senate["facets"]["chamber"]} == {
        "EK": 1,
        "TK": 2,
    }
    assert {f["value"]: f["count"] for f in senate["facets"]["kind"]} == {
        "Memorie van antwoord": 1
    }
    assert [d["key"] for d in motions["items"]] == ["motion"]
    assert {f["value"] for f in motions["facets"]["kind"]} == {
        "Memorie van toelichting",
        "Motie",
        "Memorie van antwoord",
        "Brief regering",
    }
    assert [d["key"] for d in window["items"]] == ["other", "motion"]
    assert (page["total"], page["facets"], len(page["items"])) == (None, None, 1)


_ITEM_KEYS = [
    "id",
    "key",
    "chamber",
    "kind",
    "dossier_number",
    "dossier_suffix",
    "dossier_numbers",
    "sequence",
    "number",
    "date",
    "title",
    "session_year",
    "actors",
    "dictum",
]


def test_a_listed_paper_has_the_fields_of_the_aql_object_in_its_order(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        D,
        [
            _doc(
                "full",
                ["TK", "EK"],  # both labels: the Eerste Kamer wins
                kind="Motie",
                dossier_number="37020",
                dossier_suffix="XV",
                dossier_numbers=["37020-XV"],
                sequence=7,
                number="7",
                date="2026-01-02",
                title="Titel",
                display_name="Naam",
                session_year="2025-2026",
                text="not listed",
            ),
            # no title: the display name; dossier_numbers falsy: []
            _doc(
                "bare",
                ["TK"],
                date="2026-01-01",
                title=None,
                display_name="Naam",
                dossier_numbers="",
            ),
            _doc("none", ["TK"], date="2026-01-01"),
        ],
    )

    result = list_documents(store)
    assert list(result) == ["items", "total", "facets"]
    full, bare, none = result["items"]
    assert list(full) == _ITEM_KEYS
    assert full == {
        "id": f"{D}/full",
        "key": "full",
        "chamber": "EK",
        "kind": "Motie",
        "dossier_number": "37020",
        "dossier_suffix": "XV",
        "dossier_numbers": ["37020-XV"],
        "sequence": 7,
        "number": "7",
        "date": "2026-01-02",
        "title": "Titel",
        "session_year": "2025-2026",
        "actors": None,
        "dictum": None,
    }
    assert (bare["key"], bare["chamber"], bare["title"], bare["dossier_numbers"]) == (
        "bare",
        "TK",
        "Naam",
        [],
    )
    assert none == dict.fromkeys(_ITEM_KEYS) | {
        "id": f"{D}/none",
        "key": "none",
        "chamber": "TK",
        "dossier_numbers": [],
        "date": "2026-01-01",
    }
    # a count is an int, not 1.0
    assert '"count": 1}' in json.dumps(result["facets"])


def test_papers_of_one_day_are_settled_by_key_and_paging_reaches_past_the_end(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        D,
        [
            _doc("b", ["TK"], date="2026-01-01", kind="Motie"),
            _doc("a", ["TK"], date="2026-01-01", kind="Motie"),
            _doc("C", ["TK"], date="2026-01-01", kind="Brief"),
            _doc("new", ["TK"], date="2026-02-01", kind="Brief"),
            # without a date, or with one of another type: not listed
            _doc("undated", ["TK"], kind="Brief"),
            _doc("numbered", ["TK"], date=20260101, kind="Brief"),
        ],
    )

    keys = [d["key"] for d in list_documents(store)["items"]]
    assert keys == ["new", "a", "b", "C"]
    second = list_documents(store, limit=2, offset=1)
    assert [d["key"] for d in second["items"]] == ["a", "b"]
    assert second["total"] == 4
    past = list_documents(store, limit=2, offset=10)
    assert (past["items"], past["total"]) == ([], 4)
    assert list_documents(store, offset=10, facets=False) == {
        "items": [],
        "total": None,
        "facets": None,
    }
    # the date bounds are inclusive
    day = list_documents(store, date_from="2026-01-01", date_to="2026-01-01")
    assert [d["key"] for d in day["items"]] == ["a", "b", "C"]


def test_facets_are_the_largest_first_and_equal_counts_by_value(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        D,
        [
            _doc("1", ["TK"], date="2026-01-01", kind="Motie"),
            _doc("2", ["TK"], date="2026-01-01", kind="Brief"),
            _doc("3", ["EK"], date="2026-01-01", kind="Brief"),
            _doc("4", ["EK"], date="2026-01-01", kind="Amendement"),
            _doc("5", ["EK"], date="2026-01-01"),
            _doc("6", ["TK"], date="2026-01-01", kind="Verslag"),
        ],
    )

    facets = list_documents(store)["facets"]
    assert list(facets) == ["kind", "chamber"]
    assert facets["kind"] == [
        {"value": "Brief", "count": 2},
        {"value": None, "count": 1},
        {"value": "Amendement", "count": 1},
        {"value": "Motie", "count": 1},
        {"value": "Verslag", "count": 1},
    ]
    assert all(list(f) == ["value", "count"] for f in facets["kind"])
    # chamber facet: under the kind filter, not the chamber one; kind: the other way
    filtered = list_documents(store, chambers=("EK",), kinds=("Brief", "Motie"))
    assert [d["key"] for d in filtered["items"]] == ["3"]
    assert filtered["total"] == 1
    assert filtered["facets"]["chamber"] == [
        {"value": "TK", "count": 2},
        {"value": "EK", "count": 1},
    ]
    assert filtered["facets"]["kind"] == [
        {"value": None, "count": 1},
        {"value": "Amendement", "count": 1},
        {"value": "Brief", "count": 1},
    ]


def test_a_dossier_filter_matches_a_label_in_dossier_numbers(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        D,
        [
            _doc(
                "ch", ["TK"], date="2026-01-01", dossier_numbers=["37020-XV", "36000"]
            ),
            _doc("main", ["TK"], date="2026-01-02", dossier_numbers=["37020"]),
            _doc("str", ["TK"], date="2026-01-03", dossier_numbers="37020-XV"),
        ],
    )

    chapter = list_documents(store, dossier="37020-XV")
    assert [d["key"] for d in chapter["items"]] == ["ch"]
    assert chapter["total"] == 1
    assert list_documents(store, dossier="99999")["items"] == []
