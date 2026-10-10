"""The reads of the Tweede and Eerste Kamer semantic steps on a real PostgreSQL: which papers,
memoranda, dossiers and cases each reads, in which order, with which values (nulls, missing
props and props of another type as ArangoDB saw them)."""

from __future__ import annotations

import json
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_SECOND_READING_OF,
    SOURCE_EERSTEKAMER,
    SOURCE_TK,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk

MVT = "Memorie van toelichting"
LINKER = "mvt-section-linker"
SLIM_KEYS = ["_key", "type", "labels", "props"]


def _node(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict:
    return {"_key": key, "type": node_type, "labels": labels or [], "props": props}


def _edge(src: str, dst: str, relation: str, key: str, **doc: Any) -> dict:
    return {
        "_key": key,
        "_from": src,
        "_to": dst,
        "relation": relation,
        "source": "test",
        **doc,
    }


def _seed(store: GraphStore, collection: str, *docs: dict[str, Any]) -> None:
    store.bulk_insert_or_update_nodes(collection, list(docs))


def _edges(store: GraphStore, *edges: dict[str, Any]) -> None:
    store.bulk_insert_or_update_edges(list(edges))


# ── the Eerste Kamer papers and their dossiers (moved from tests/integration) ──


def _dossiers(store: GraphStore) -> None:
    _seed(
        store,
        COLLECTION_DOSSIERS,
        _node("37020", "dossier", number="37020"),
        _node("37020_xv", "dossier", number="37020", suffix="XV"),
    )


def _paper(key: str, number: Any, suffix: Any = None, **props: Any) -> dict:
    props = {"source": SOURCE_EERSTEKAMER, "dossier_number": number, **props}
    if suffix is not None:
        props["dossier_suffix"] = suffix
    return _node(key, "document", **props)


def test_a_paper_belongs_to_the_dossier_with_its_number_and_addition(
    store: GraphStore,
) -> None:
    _dossiers(store)
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _paper("ek_chapter", "37020", "XV"),
        _paper("ek_nota", "37020"),
        _paper("ek_unknown", "37021"),  # no such dossier in the graph
        _paper("tk_paper", "37020", source=SOURCE_TK),  # not an Eerste Kamer paper
    )
    rows = semantic_tk.ek_papers_in_tk_dossiers(store)
    assert sorted((row["document_key"], row["dossier_key"]) for row in rows) == [
        ("ek_chapter", "37020_xv"),
        ("ek_nota", "37020"),
    ]


def test_a_paper_on_more_than_one_dossier_is_matched_to_the_others_by_label(
    store: GraphStore,
) -> None:
    _seed(
        store,
        COLLECTION_DOSSIERS,
        _node("33081", "dossier", number="33081", label="33081"),
        _node("33082", "dossier", number="33082", label="33082"),
        _node("36200_xvi", "dossier", number="36200", suffix="XVI", label="36200-XVI"),
    )
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _paper("ek_two", "33081", dossier_numbers=["33081", "33082"]),
        _paper("ek_chapter", "33626", dossier_numbers=["33626", "36200-XVI", "99999"]),
        _paper("ek_one", "33081", dossier_numbers=["33081"]),
        _paper("tk_two", "33081", source=SOURCE_TK, dossier_numbers=["33081", "33082"]),
    )
    rows = semantic_tk.ek_papers_in_other_dossiers(store)
    # past the first number; a dossier not in the graph and a TK paper give nothing
    assert [
        (r["document_key"], r["dossier_key"], r["dossier_suffix"]) for r in rows
    ] == [
        ("ek_chapter", "36200_xvi", "XVI"),
        ("ek_two", "33082", None),
    ]


def test_every_paper_is_linked_not_the_first_ten_thousand(store: GraphStore) -> None:
    _dossiers(store)
    papers = [_paper(f"ek_{n}", "37020") for n in range(10_001)]
    for start in range(0, len(papers), 2_000):
        _seed(store, COLLECTION_DOCUMENTS, *papers[start : start + 2_000])
    assert sum(1 for _ in semantic_tk.ek_papers_in_tk_dossiers(store)) == 10_001


def test_a_paper_number_of_another_type_is_read_as_its_text(store: GraphStore) -> None:
    _dossiers(store)
    _seed(
        store,
        COLLECTION_DOSSIERS,
        _node("dtrue", "dossier", number="true"),
        _node("37030_5", "dossier", number="37030", suffix=5),
        _node("37030_s5", "dossier", number="37030", suffix="5"),
        # two dossiers of one number: the first by key
        _node("37040b", "dossier", number="37040"),
        _node("37040a", "dossier", number="37040", suffix=None),
    )
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _paper("ek_int", 37020),
        _paper("ek_float", 37020.0, ""),
        _paper("ek_zero", "37020", 0),  # a false suffix is no suffix
        _paper("ek_true", True),
        _paper("ek_num_suffix", "37030", 5),  # 5 is not "5"
        _paper("ek_array", [37020]),
        _paper("ek_null", None),
        _paper("ek_lower", "37020", "xv"),
        _paper("ek_twice", "37040"),
    )
    rows = list(semantic_tk.ek_papers_in_tk_dossiers(store))
    assert rows == [
        {
            "document_key": "ek_float",
            "dossier_key": "37020",
            "dossier_number": 37020.0,
            "dossier_suffix": "",
        },
        {
            "document_key": "ek_int",
            "dossier_key": "37020",
            "dossier_number": 37020,
            "dossier_suffix": None,
        },
        {
            "document_key": "ek_num_suffix",
            "dossier_key": "37030_5",
            "dossier_number": "37030",
            "dossier_suffix": 5,
        },
        {
            "document_key": "ek_true",
            "dossier_key": "dtrue",
            "dossier_number": True,
            "dossier_suffix": None,
        },
        {
            "document_key": "ek_twice",
            "dossier_key": "37040a",
            "dossier_number": "37040",
            "dossier_suffix": None,
        },
        {
            "document_key": "ek_zero",
            "dossier_key": "37020",
            "dossier_number": "37020",
            "dossier_suffix": 0,
        },
    ]
    assert json.dumps(rows[0]).startswith('{"document_key": "ek_float", "dossier_key"')


# ── the memoranda of a second reading (moved from tests/integration) ──────────


def _writer_node(collection: str, node_type: NodeType, key: str, **props: Any) -> Node:
    return Node(
        collection=collection, type=node_type, key=key, labels=["TK"], props=props
    )


def test_the_memorandum_of_the_first_reading_explains_what_the_second_made_law(
    store: GraphStore,
) -> None:
    article = f"{COLLECTION_ARTICLES}/bwbr0001840_13"
    first, second = f"{COLLECTION_DOSSIERS}/35418", f"{COLLECTION_DOSSIERS}/35785"
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _writer_node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "35418",
                    number="35418",
                    label="35418",
                ),
                _writer_node(
                    COLLECTION_DOSSIERS,
                    NodeType.DOSSIER,
                    "35785",
                    number="35785",
                    label="35785",
                ),
                _writer_node(
                    COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "mvt_first", kind=MVT
                ),
                _writer_node(
                    COLLECTION_DOCUMENTS, NodeType.DOCUMENT, "mvt_second", kind=MVT
                ),
                _writer_node(
                    COLLECTION_INSTRUMENTS,
                    NodeType.INSTRUMENT,
                    "stb_2022_332",
                    publication_kind="Stb",
                ),
                _writer_node(
                    COLLECTION_ARTICLES,
                    NodeType.ARTICLE,
                    "bwbr0001840_13",
                    bwb_id="BWBR0001840",
                    article_number="13",
                ),
            ]
        )
    edges = EdgeWriter(store, what=None)
    edges.add(
        f"{COLLECTION_DOCUMENTS}/mvt_first", first, RELATION_PART_OF, source="test"
    )
    edges.add(
        f"{COLLECTION_DOCUMENTS}/mvt_second", second, RELATION_PART_OF, source="test"
    )
    stb = f"{COLLECTION_INSTRUMENTS}/stb_2022_332"
    edges.add(stb, second, RELATION_LEGISLATED_IN, source="test")
    edges.add(stb, article, RELATION_AMENDS, source="test")
    edges.flush()

    def targets() -> dict[str, list[str]]:
        rows = semantic_tk.memorandum_targets(store, sections_source=LINKER)
        return {row["document"]: row["targets"] for row in rows}

    assert targets() == {f"{COLLECTION_DOCUMENTS}/mvt_second": [article]}

    edges.add(second, first, RELATION_SECOND_READING_OF, source="test")
    edges.flush()
    assert targets() == {
        f"{COLLECTION_DOCUMENTS}/mvt_second": [article],
        f"{COLLECTION_DOCUMENTS}/mvt_first": [article],
    }


# ── a graph of memoranda, dossiers, instruments and articles ──────────────────


def _graph(store: GraphStore) -> None:
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _node(
            "mvt1",
            "document",
            ["TK"],
            kind=MVT,
            text="Zie de Eerste Lezing.",
            structure_quality="explicit",
            sections=[{"heading": "Artikel 1"}],
            budget=False,
        ),
        _node("mvt_arr", "document", ["TK"], kind=[MVT], text="eerste lezing"),
        _node(
            "mvt_budget",
            "document",
            ["TK"],
            kind="memorie van toelichting",
            text="eerste lezing",
            budget=True,
            structure_quality="explicit",
        ),
        _node("mvt_ek", "document", ["EK"], kind=MVT, text="eerste lezing"),
        _node("mvt_lone", "document", ["TK"], kind=MVT, text="eerste lezing"),
        _node("motie", "document", ["TK"], kind="Motie", text="eerste lezing"),
    )
    _seed(
        store,
        COLLECTION_DOSSIERS,
        _node("36000", "dossier", number="36000", label="36000"),
        _node("36001", "dossier", number="36001", label=36001),
        _node("36002", "dossier", number="36002", label="36002"),
    )
    _seed(
        store,
        COLLECTION_INSTRUMENTS,
        _node("bwbr1", "instrument", bwb_id="BWBR1", title="Wet A", short_title="wa"),
        _node("stb1", "instrument", bwb_id=None),
        _node("bwbr2", "instrument", bwb_id="BWBR2", citation_title="Wet B"),
        _node("num", "instrument", bwb_id=7, title="Numeriek"),
    )
    _seed(
        store,
        COLLECTION_ARTICLES,
        _node("bwbr2_1", "article", bwb_id="BWBR2", article_number="1"),
        _node("bwbr2_2", "article", bwb_id="BWBR2", article_number=2),
        _node("noart", "article", bwb_id="BWBR2"),
        _node("numart", "article", bwb_id=7, article_number="3"),
    )
    _edges(
        store,
        _edge("documents/mvt1", "dossiers/36000", "PART_OF", "p1"),
        _edge("documents/mvt1", "dossiers/gone", "PART_OF", "p2"),
        _edge("documents/mvt1", "dossiers/36001", "PART_OF", "p3"),
        _edge("documents/mvt1", "dossiers/36000", "PART_OF", "p4"),
        _edge("documents/mvt1", "cases/c1", "PART_OF", "p5"),
        _edge("documents/mvt_arr", "dossiers/36002", "PART_OF", "p6"),
        _edge("documents/mvt_budget", "dossiers/36000", "PART_OF", "p7"),
        _edge("documents/mvt_ek", "dossiers/36000", "PART_OF", "p8"),
        _edge("dossiers/36002", "dossiers/36001", "SECOND_READING_OF", "s1"),
        _edge("instruments/bwbr1", "dossiers/36000", "LEGISLATED_IN", "l1"),
        _edge("instruments/stb1", "dossiers/36002", "LEGISLATED_IN", "l2"),
        _edge("instruments/bwbr1", "dossiers/36002", "LEGISLATED_IN", "l3"),
        _edge("documents/motie", "dossiers/36000", "LEGISLATED_IN", "l4"),
        _edge("instruments/num", "dossiers/36001", "LEGISLATED_IN", "l5"),
        # the changes, by key: c0 before c1 although written after it
        _edge("instruments/stb1", "articles/bwbr2_1", "AMENDS", "c1",
              meta={"article_version": "v1"}),
        _edge("instruments/stb1", "articles/bwbr2_2", "INTRODUCES", "c2"),
        _edge("instruments/stb1", "articles/bwbr2_1", "AMENDS", "c3",
              meta={"article_version": "v1"}),
        _edge("instruments/stb1", "articles/noart", "AMENDS", "c4"),
        _edge("instruments/stb1", "articles/gone", "AMENDS", "c5"),
        _edge("instruments/stb1", "articles/bwbr2_1", "AMENDS", "c6",
              meta={"article_version": 5}),
        _edge("instruments/stb1", "articles/bwbr2_1", "REFERS_TO", "c7"),
        _edge("instruments/bwbr1", "articles/bwbr2_1", "AMENDS", "c0", meta="flat"),
        _edge("instruments/num", "articles/numart", "AMENDS", "c8"),
        _edge("documents/mvt1", "articles/bwbr2_2", "EXPLAINS", "x1", source=LINKER),
        _edge("documents/mvt1", "article_versions/v1", "EXPLAINS", "x2", source="o"),
    )  # fmt: skip


def test_second_reading_memoranda_are_tk_memoranda_with_their_dossier_labels(
    store: GraphStore,
) -> None:
    _graph(store)
    rows = list(semantic_tk.second_reading_memoranda(store))
    assert rows == [
        # a kind of another type is read as its JSON text
        {"labels": ["36002"], "text": "eerste lezing"},
        {"labels": ["36000"], "text": "eerste lezing"},
        {"labels": [], "text": "eerste lezing"},
        # a dossier gone is a null label; a case is no dossier; a label once per edge
        {"labels": ["36000", None, 36001, "36000"], "text": "Zie de Eerste Lezing."},
    ]
    assert [list(row) for row in rows] == [["labels", "text"]] * 4


def test_memorandum_targets_less_what_the_sections_explain(store: GraphStore) -> None:
    _graph(store)
    rows = list(semantic_tk.memorandum_targets(store, sections_source=LINKER))
    stb1 = [
        "article_versions/v1",
        "articles/bwbr2_2",
        "articles/noart",
        "articles/gone",
        "article_versions/5",
    ]
    assert rows == [
        # its own dossier only: stb1, then bwbr1
        {"document": "documents/mvt_arr", "targets": [*stb1, "articles/bwbr2_1"]},
        {"document": "documents/mvt_budget", "targets": ["articles/bwbr2_1"]},
        # not a TK paper, still a memorandum
        {"document": "documents/mvt_ek", "targets": ["articles/bwbr2_1"]},
        # bwbr1 (36000; its edge c0 has a meta that is no object: no version), num
        # (36001), stb1 (36002, whose second reading 36001 is); less bwbr2_2
        {
            "document": "documents/mvt1",
            "targets": [
                "articles/bwbr2_1",
                "articles/numart",
                *(t for t in stb1 if t != "articles/bwbr2_2"),
            ],
        },
    ]
    assert [list(row) for row in rows] == [["document", "targets"]] * 4


def test_memorandum_targets_are_the_instruments_without_a_change(
    store: GraphStore,
) -> None:
    _seed(store, COLLECTION_DOCUMENTS, _node("m", "document", kind=MVT))
    _edges(
        store,
        _edge("documents/m", "dossiers/d", "PART_OF", "p"),
        _edge("instruments/b", "dossiers/d", "LEGISLATED_IN", "l2"),
        _edge("instruments/a", "dossiers/d", "LEGISLATED_IN", "l1"),
        _edge("instruments/b", "dossiers/d", "LEGISLATED_IN", "l3"),
        _edge("documents/m", "instruments/a", "EXPLAINS", "x", source=LINKER),
    )
    rows = list(semantic_tk.memorandum_targets(store, sections_source=LINKER))
    assert rows == [{"document": "documents/m", "targets": ["instruments/b"]}]


def test_memoranda_with_sections(store: GraphStore) -> None:
    _graph(store)
    rows = list(
        semantic_tk.memoranda_with_sections(
            store, qualities=["explicit", "implicit"], batch_size=1
        )
    )
    assert [row["document"] for row in rows] == ["documents/mvt1"]
    row = rows[0]
    assert list(row) == [
        "document",
        "text",
        "sections",
        "own",
        "changes",
        "laws",
        "bill",
    ]
    assert row["text"] == "Zie de Eerste Lezing."
    assert row["bill"] is None  # its dossiers have no bill
    assert row["sections"] == [{"heading": "Artikel 1"}]
    # bwbr1 (via 36000), num (via 36001); stb1 has no BWB id, gone no instrument
    assert row["own"] == ["BWBR1", 7]
    change = {"bwb_id": "BWBR2", "number": "1", "article": "articles/bwbr2_1"}
    assert row["changes"] == [
        {**change, "version": None, "relation": "AMENDS"},
        {"bwb_id": 7, "number": "3", "article": "articles/numart", "version": None,
         "relation": "AMENDS"},
        {**change, "version": "v1", "relation": "AMENDS"},
        {"bwb_id": "BWBR2", "number": 2, "article": "articles/bwbr2_2", "version": None,
         "relation": "INTRODUCES"},
        {**change, "version": 5, "relation": "AMENDS"},
    ]  # fmt: skip
    assert list(row["changes"][0]) == [
        "bwb_id",
        "number",
        "article",
        "version",
        "relation",
    ]
    assert row["laws"] == [
        {"bwb_id": "BWBR1", "names": ["Wet A", None], "codes": ["wa"]},
        {"bwb_id": "BWBR2", "names": [None, "Wet B"], "codes": [None]},
        {"bwb_id": 7, "names": ["Numeriek", None], "codes": [None]},
    ]
    assert list(row["laws"][0]) == ["bwb_id", "names", "codes"]


def test_the_bill_of_a_memorandum_is_the_first_of_its_own_dossiers(
    store: GraphStore,
) -> None:
    """The memorandum explains the bill as it was sent: the first Voorstel van wet of a
    dossier it is part of, not a changed one, nor one of another dossier."""
    _graph(store)
    bill = "Voorstel van wet"
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _node("bill_late", "document", ["TK"], kind=bill, date="2021-01-01", text="late"),
        _node("bill_first", "document", ["TK"], kind=bill, date="2020-01-01", text="eerst"),
        _node("changed", "document", ["TK"], kind=f"Gewijzigd {bill.lower()}",
              date="2019-01-01", text="gewijzigd"),
        _node("other", "document", ["TK"], kind=bill, date="2018-01-01", text="ander"),
    )  # fmt: skip
    _edges(
        store,
        _edge("documents/bill_late", "dossiers/36001", "PART_OF", "b1"),
        _edge("documents/bill_first", "dossiers/36001", "PART_OF", "b2"),
        _edge("documents/changed", "dossiers/36001", "PART_OF", "b3"),
        _edge("documents/other", "dossiers/36002", "PART_OF", "b4"),
    )

    (row,) = semantic_tk.memoranda_with_sections(
        store, qualities=["explicit", "implicit"], batch_size=1
    )

    assert row["bill"] == "eerst"


def test_memoranda_with_sections_change_once_where_first_seen(
    store: GraphStore,
) -> None:
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _node("m", "document", kind=MVT, text="t", structure_quality="explicit"),
        _node("n", "document", kind=MVT, text="t", structure_quality="implicit"),
        _node("o", "document", kind=MVT, text=None, structure_quality="explicit"),
        _node("q", "document", kind=MVT, text="t", structure_quality=["explicit"]),
        _node("r", "document", kind=MVT, text="t", structure_quality="explicit",
              budget="true"),
    )  # fmt: skip
    _seed(
        store,
        COLLECTION_ARTICLES,
        _node("a1", "article", bwb_id="BWBR9", article_number="1"),
    )
    _edges(
        store,
        *(
            _edge(f"documents/{k}", "dossiers/d", "PART_OF", f"p{k}")
            for k in "mnoqr"
        ),
        _edge("instruments/i", "dossiers/d", "LEGISLATED_IN", "l"),
        _edge("instruments/i", "articles/a1", "AMENDS", "e1",
              meta={"article_version": 1.5}),
        _edge("instruments/i", "articles/a1", "REPEALS", "e2"),
        _edge("instruments/i", "articles/a1", "AMENDS", "e3",
              meta={"article_version": 1.50}),
        _edge("instruments/i", "articles/a1", "AMENDS", "e4",
              meta={"article_version": "1.5"}),
    )  # fmt: skip
    rows = list(
        semantic_tk.memoranda_with_sections(
            store, qualities=["explicit"], batch_size=10
        )
    )
    assert [row["document"] for row in rows] == ["documents/m", "documents/r"]
    assert [(c["version"], c["relation"]) for c in rows[0]["changes"]] == [
        (1.5, "AMENDS"),
        (None, "REPEALS"),
        ("1.5", "AMENDS"),
    ]
    assert rows[0]["own"] == [] and rows[0]["laws"] == []
    assert (
        list(semantic_tk.memoranda_with_sections(store, qualities=[], batch_size=10))
        == []
    )


# ── the Tweede Kamer papers ───────────────────────────────────────────────────


def _papers(store: GraphStore) -> None:
    _seed(
        store,
        COLLECTION_DOCUMENTS,
        _node("b", "document", ["TK"], external_id="e2", date="2025-01-01", kind="Brief",
              title="B", zeta=1, display_name="b", text="x", bwb_id="BWBR1"),
        _node("A", "document", ["TK"], external_id=5, date=["x"], text=""),
        _node("a", "document", ["TK"], external_id="e1", date="2024-12-31", text=7),
        _node("c", "document", ["TK"], date=None, text=None, bwb_id="BWBR2"),
        _node("d", "document", ["TK"], date=20250101, text="t", bwb_id=None),
        _node("ek", "document", ["EK"], external_id="e3", date="2026-01-01", text="t",
              bwb_id="BWBR3"),
    )  # fmt: skip


def test_tk_documents_whole_by_key(store: GraphStore) -> None:
    _papers(store)
    rows = list(semantic_tk.tk_documents(store, None))
    assert [row["_key"] for row in rows] == ["A", "a", "b", "c", "d"]
    assert rows[2] == {
        "_key": "b",
        "_id": "documents/b",
        "type": "document",
        "labels": ["TK"],
        "props": {
            "external_id": "e2",
            "date": "2025-01-01",
            "kind": "Brief",
            "title": "B",
            "zeta": 1,
            "display_name": "b",
            "text": "x",
            "bwb_id": "BWBR1",
        },
    }
    picked = semantic_tk.tk_documents(store, ["e2", "e1", "5", "e3", "nope"])
    assert [row["_key"] for row in picked] == ["a", "b"]
    assert list(semantic_tk.tk_documents(store, [])) == []


def test_tk_document_titles_since_a_date(store: GraphStore) -> None:
    _papers(store)
    rows = list(semantic_tk.tk_document_titles(store, None))
    assert [row["_key"] for row in rows] == ["A", "a", "b", "c", "d"]
    assert [list(row) for row in rows] == [SLIM_KEYS] * 5
    assert rows[2]["props"] == {
        "display_name": "b",
        "kind": "Brief",
        "title": "B",
    }
    assert list(rows[2]["props"]) == ["display_name", "kind", "title"]
    assert rows[1]["props"] == {}
    # an array sorts above every string; a number and null below
    since = semantic_tk.tk_document_titles(store, "2025-01-01")
    assert [row["_key"] for row in since] == ["A", "b"]
    assert [r["_key"] for r in semantic_tk.tk_document_titles(store, "9999")] == ["A"]


def test_tk_documents_to_scan_for_amendments(store: GraphStore) -> None:
    _papers(store)
    rows = list(semantic_tk.tk_documents_to_scan_for_amendments(store, []))
    assert rows == [
        {
            "_key": "b",
            "type": "document",
            "labels": ["TK"],
            "props": {"bwb_id": "BWBR1", "text": "x"},
        }
    ]
    amending = ["documents/a", "documents/A", "documents/d", "documents/ek"]
    rows = list(semantic_tk.tk_documents_to_scan_for_amendments(store, amending))
    # A has an empty text, ek is no TK paper; a text of another type counts
    assert [(row["_key"], row["props"]) for row in rows] == [
        ("a", {"text": 7}),
        ("b", {"bwb_id": "BWBR1", "text": "x"}),
        ("d", {"bwb_id": None, "text": "t"}),
    ]


def test_amended_instruments_by_edge_key(store: GraphStore) -> None:
    _seed(
        store,
        COLLECTION_INSTRUMENTS,
        _node("i1", "instrument", bwb_id="BWBR1"),
        _node("i2", "instrument", bwb_id=None),
        _node("i3", "instrument", bwb_id=7),
    )
    _edges(
        store,
        _edge("documents/x", "instruments/i3", "AMENDS", "b"),
        _edge("documents/y", "instruments/i1", "AMENDS", "a"),
        _edge("documents/y", "instruments/i2", "AMENDS", "c"),
        _edge("documents/y", "instruments/gone", "AMENDS", "d"),
        _edge("cases/z", "instruments/i1", "AMENDS", "e"),
        _edge("documents/z", "instruments/i1", "REFERS_TO", "f"),
    )
    rows = list(semantic_tk.amended_instruments(store))
    assert rows == [
        {"document_id": "documents/y", "bwb_id": "BWBR1"},
        {"document_id": "documents/x", "bwb_id": 7},
    ]
    assert list(rows[0]) == ["document_id", "bwb_id"]


# ── dossiers and cases ────────────────────────────────────────────────────────


def test_dossier_ids_and_refs_by_key(store: GraphStore) -> None:
    _seed(
        store,
        COLLECTION_DOSSIERS,
        _node("b", "dossier", title="T", number="2", label="2", zeta=1, suffix=None),
        _node("B", "dossier", number=3),
        _node("a", "dossier"),
    )
    assert list(semantic_tk.dossier_ids(store)) == [
        "dossiers/a",
        "dossiers/B",
        "dossiers/b",
    ]
    refs = list(semantic_tk.dossier_refs(store))
    assert refs == [
        {},
        {"number": 3},
        {"label": "2", "number": "2", "suffix": None, "title": "T"},
    ]
    assert list(refs[2]) == ["label", "number", "suffix", "title"]


def test_dossier_outcome_signals(store: GraphStore) -> None:
    _seed(
        store,
        COLLECTION_DOSSIERS,
        _node("d1", "dossier", outcome="aangenomen", kind="Wetgeving", closed=True,
              zeta=1, ek_rejected=False),
        _node("d2", "dossier"),
    )  # fmt: skip
    _seed(
        store,
        COLLECTION_INSTRUMENTS,
        _node(
            "i1", "instrument", date_published="2025-03-01", date_signed="2025-02-01"
        ),
        _node("i2", "instrument", date_published="2025-04-01"),
    )
    _seed(
        store,
        "decisions",
        _node("b", "decision", primary_case_kind="Wetgeving", date="2025-01-02",
              passed=True, decision_text="x", extra=1),
        _node("a", "decision", primary_case_kind="Wetgeving", passed=False),
        _node("c", "decision", primary_case_kind=["Wetgeving"]),
        _node("ek", "decision", chamber="EK", date="2025-05-01", result="aangenomen",
              kind="Hamerstuk", zeta=2),
        _node("Ek", "decision", chamber="EK", date="2025-05-01"),
    )  # fmt: skip
    _edges(
        store,
        _edge("instruments/i2", "dossiers/d1", "LEGISLATED_IN", "l2"),
        _edge("instruments/i1", "dossiers/d1", "LEGISLATED_IN", "l1"),
        _edge("instruments/gone", "dossiers/d1", "LEGISLATED_IN", "l3"),
        _edge("decisions/b", "dossiers/d1", "ABOUT", "e1"),
        _edge("decisions/a", "dossiers/d1", "ABOUT", "e2"),
        _edge("decisions/a", "dossiers/d1", "ABOUT", "e3"),
        _edge("decisions/c", "dossiers/d1", "ABOUT", "e4"),
        _edge("decisions/ek", "dossiers/d1", "ABOUT", "e5"),
        _edge("decisions/Ek", "dossiers/d1", "ABOUT", "e6"),
        _edge("decisions/gone", "dossiers/d1", "ABOUT", "e7"),
        _edge("activities/x", "dossiers/d1", "ABOUT", "e8"),
    )
    ids = ["dossiers/d2", "dossiers/nope", "dossiers/d1", "dossiers/d2"]
    rows = list(
        semantic_tk.dossier_outcome_signals(
            store, ids, bill_case_kinds=["Wetgeving", "Initiatief"]
        )
    )
    empty = {
        "key": "d2",
        "props": {},
        "publications": [],
        "bill_decisions": [],
        "ek_votes": [],
    }
    assert rows[0] == empty and rows[2] == empty
    assert len(rows) == 3
    d1 = rows[1]
    assert list(d1) == ["key", "props", "publications", "bill_decisions", "ek_votes"]
    assert d1["key"] == "d1"
    assert list(d1["props"].items()) == [
        ("closed", True),
        ("ek_rejected", False),
        ("kind", "Wetgeving"),
        ("outcome", "aangenomen"),
    ]
    assert d1["publications"] == [
        {"date_published": "2025-03-01", "date_signed": "2025-02-01"},
        {"date_published": "2025-04-01", "date_signed": None},
    ]
    # by decision id, once per edge; the kept props in byte order
    assert d1["bill_decisions"] == [
        {"passed": False},
        {"passed": False},
        {"date": "2025-01-02", "decision_text": "x", "passed": True},
    ]
    assert list(d1["bill_decisions"][2]) == ["date", "decision_text", "passed"]
    assert d1["ek_votes"] == [
        {"id": "decisions/Ek", "date": "2025-05-01"},
        {"id": "decisions/ek", "date": "2025-05-01", "kind": "Hamerstuk",
         "result": "aangenomen"},
    ]  # fmt: skip
    assert list(d1["ek_votes"][1]) == ["id", "date", "kind", "result"]
    assert (
        list(semantic_tk.dossier_outcome_signals(store, [], bill_case_kinds=[])) == []
    )


def test_related_cases_with_a_length(store: GraphStore) -> None:
    _seed(
        store,
        "cases",
        _node("c1", "case", external_id="C1", kind="Motie", dossier_numbers=["1"],
              related_cases=[{"dossier_numbers": ["2"]}]),
        _node("c2", "case", related_cases=[]),
        _node("c3", "case", related_cases="x"),
        _node("c4", "case", related_cases={}),
        _node("c5", "case", related_cases=0),
        _node("c6", "case", related_cases=False),
        _node("c7", "case", related_cases=True),
        _node("c8", "case"),
        _node("C0", "case", related_cases={"a": 1}, external_id=8),
    )  # fmt: skip
    rows = list(semantic_tk.related_cases(store))
    assert rows == [
        {"id": 8, "kind": None, "dossier_numbers": None, "related_cases": {"a": 1}},
        {
            "id": "C1",
            "kind": "Motie",
            "dossier_numbers": ["1"],
            "related_cases": [{"dossier_numbers": ["2"]}],
        },
        {"id": None, "kind": None, "dossier_numbers": None, "related_cases": "x"},
        {"id": None, "kind": None, "dossier_numbers": None, "related_cases": 0},
        {"id": None, "kind": None, "dossier_numbers": None, "related_cases": True},
    ]
    assert list(rows[0]) == ["id", "kind", "dossier_numbers", "related_cases"]
