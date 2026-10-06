"""The removals of the normalize and semantic phases and the reads of the gaps on a real
PostgreSQL: which nodes and edges go, which stay, the counts, and the rows and order of
every gaps list."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_EU_CELEX,
    RELATION_ANSWERS,
    SOURCE_EURLEX,
    SOURCE_TK,
)
from lawgraph.core.judgments import PROCEDURE_PRELIMINARY_RULING
from lawgraph.db import GraphStore, raw_source_doc
from lawgraph.db.queries import _chunks as chunks
from lawgraph.db.queries import gaps as gap_queries
from lawgraph.db.queries.normalize import edges as normalize_edges
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.store import raw_key


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": [], "props": props}


def _tk(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": ["TK"], "props": props}


def _edge(
    key: str,
    source_id: str,
    target_id: str,
    relation: str = "REFERS_TO",
    source: str = "s",
    **rest: Any,
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source_id,
        "_to": target_id,
        "relation": relation,
        "source": source,
        **rest,
    }


def _edge_keys(store: GraphStore) -> list[str]:
    return list(store.query("SELECT key FROM edges ORDER BY key"))


def _node_keys(store: GraphStore, table: str) -> list[str]:
    return list(store.query(f"SELECT key FROM {table} ORDER BY key"))


# ── semantic: remove what a step no longer derives ───────────────────────────


@pytest.fixture()
def derived(store: GraphStore) -> GraphStore:
    a, b, c = "articles/a", "articles/b", "articles/c"
    store.bulk_insert_or_update_edges(
        [
            _edge("ab", a, b),
            _edge("ac", a, c),
            _edge("ba", b, a),
            _edge("bc", b, c),
            _edge("ca", c, a),
            _edge("a-other-source", a, b, source="other"),
            _edge("a-other-relation", a, c, relation="AMENDS"),
            _edge("c-amends-a", c, a, relation="AMENDS"),
        ]
    )
    return store


def test_remove_edges_of_source_except_keeps_the_kept_and_the_others(
    derived: GraphStore,
) -> None:
    removed = semantic_edges.remove_edges_of_source_except(
        derived, "REFERS_TO", "s", ["ab", "ca"]
    )
    assert removed == 3  # ac, ba, bc
    assert _edge_keys(derived) == sorted(
        ["ab", "ca", "a-other-source", "a-other-relation", "c-amends-a"]
    )


def test_remove_edges_of_source_except_with_nothing_kept(derived: GraphStore) -> None:
    assert semantic_edges.remove_edges_of_source_except(derived, "AMENDS", "s", []) == 2
    assert semantic_edges.remove_edges_of_source_except(derived, "AMENDS", "s", []) == 0


def test_remove_edges_from_per_node_keep_and_chunks(derived: GraphStore) -> None:
    removed = semantic_edges.remove_edges_from(
        derived,
        "REFERS_TO",
        "s",
        ["articles/a", "articles/b", "articles/missing"],
        # a keeps ab; b keeps "ac", which is no edge of b: bc and ba both go
        {"articles/a": {"ab"}, "articles/b": {"ac"}, "articles/c": {"ca"}},
        chunk=1,
    )
    assert removed == 3  # ac, ba, bc
    assert _edge_keys(derived) == sorted(
        ["ab", "ca", "a-other-source", "a-other-relation", "c-amends-a"]
    )


def test_remove_edges_from_a_node_without_keep_loses_them_all(
    derived: GraphStore,
) -> None:
    assert (
        semantic_edges.remove_edges_from(derived, "REFERS_TO", "s", ["articles/c"], {})
        == 1
    )
    assert "ca" not in _edge_keys(derived)
    assert semantic_edges.remove_edges_from(derived, "REFERS_TO", "s", [], {}) == 0


def test_remove_edges_to_per_node_keep_and_relations(derived: GraphStore) -> None:
    removed = semantic_edges.remove_edges_to(
        derived,
        ["REFERS_TO", "AMENDS"],
        "s",
        ["articles/a", "articles/c"],
        {"articles/a": {"ca"}},
        chunk=1,
    )
    # into a: ba and c-amends-a go, ca stays; into c: ac, bc, a-other-relation go
    assert removed == 5
    assert _edge_keys(derived) == sorted(["ab", "ca", "a-other-source"])


# ── normalize: nodes and edges that went ─────────────────────────────────────


@pytest.fixture()
def tk_graph(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node("d1", external_id="r1"),
            _node("d2", external_id="r2"),
            _node("d3", external_ids=["r1", "r3"]),  # made of r1 and r3
            _node("d4", external_ids=["r1", "r9"]),  # r9 is still there
            _node("d5", external_ids=[], external_id="r1"),  # [] is truthy: no fallback
            _node("d6", external_ids=["r1", 7]),  # 7 is no record id
            _node("d7"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("e1", "decisions/d1", "factions/f", meta={"record_ids": ["r1"]}),
            _edge("e2", "members/m", "decisions/d1", meta={"record_ids": ["r1", "r2"]}),
            _edge(
                "e3", "decisions/d2", "factions/f", meta={"record_ids": ["r2", "r9"]}
            ),
            _edge("e4", "decisions/d7", "factions/f", meta={"record_ids": ["r3"]}),
            _edge("e5", "decisions/d7", "factions/g", meta={"record_ids": ["r1", 5]}),
            _edge("e6", "decisions/d7", "factions/h", meta={"record_ids": []}),
            _edge("e7", "decisions/d7", "factions/i"),
            _edge("e8", "decisions/d3", "decisions/d7"),
        ]
    )
    return store


def test_remove_nodes_takes_their_edges_along(tk_graph: GraphStore) -> None:
    removed = normalize_edges.remove_nodes(tk_graph, "decisions", ["d1", "dx", "d3"])
    assert removed == 2  # dx is no node
    assert _node_keys(tk_graph, "decisions") == ["d2", "d4", "d5", "d6", "d7"]
    # e1 from d1, e2 into d1, e8 from d3
    assert _edge_keys(tk_graph) == ["e3", "e4", "e5", "e6", "e7"]


def test_remove_nodes_in_chunks(
    tk_graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(normalize_edges, "_REMOVE_CHUNK", 1)
    assert normalize_edges.remove_nodes(tk_graph, "decisions", ["d1", "d2"]) == 2
    assert normalize_edges.remove_nodes(tk_graph, "decisions", []) == 0


def test_remove_nodes_except(tk_graph: GraphStore) -> None:
    assert normalize_edges.remove_nodes_except(tk_graph, "decisions", ["d1", "d7"]) == 5
    assert _node_keys(tk_graph, "decisions") == ["d1", "d7"]
    assert len(_edge_keys(tk_graph)) == 8  # the edges stay, as in ArangoDB


def test_remove_nodes_of_records(tk_graph: GraphStore) -> None:
    assert normalize_edges.remove_nodes_of_records(tk_graph, "decisions", []) == 0
    removed = normalize_edges.remove_nodes_of_records(
        tk_graph, "decisions", ["r1", "r3"]
    )
    # d1 (r1), d3 (r1, r3), d5 ([] and r1); not d4 (r9), d6 (7), d2, d7
    assert removed == 3
    assert _node_keys(tk_graph, "decisions") == ["d2", "d4", "d6", "d7"]
    assert _edge_keys(tk_graph) == ["e3", "e4", "e5", "e6", "e7"]


def test_remove_edges_of_records(tk_graph: GraphStore) -> None:
    assert normalize_edges.remove_edges_of_records(tk_graph, []) == 0
    removed = normalize_edges.remove_edges_of_records(tk_graph, ["r1", "r2", "r3"])
    # e1, e2, e4 are made of them alone; e3 names r9, e5 names 5, e6-e8 name none
    assert removed == 3
    assert _edge_keys(tk_graph) == ["e3", "e5", "e6", "e7", "e8"]


def test_remove_edges_of_records_in_chunks_against_all(
    tk_graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(normalize_edges, "_REMOVE_CHUNK", 1)
    # e2 (r1, r2) is in two chunks and goes once; it is made of the whole list alone
    assert normalize_edges.remove_edges_of_records(tk_graph, ["r1", "r2"]) == 2
    assert _edge_keys(tk_graph) == ["e3", "e4", "e5", "e6", "e7", "e8"]


def test_remove_edges_into_except(tk_graph: GraphStore) -> None:
    removed = normalize_edges.remove_edges_into_except(
        tk_graph, "REFERS_TO", ["factions/f", "factions/g"], ["e1"]
    )
    assert removed == 3  # e3, e4, e5
    assert _edge_keys(tk_graph) == ["e1", "e2", "e6", "e7", "e8"]


def test_remove_edges_except(tk_graph: GraphStore) -> None:
    tk_graph.bulk_insert_or_update_edges([_edge("x1", "a/1", "b/1", relation="AMENDS")])
    assert normalize_edges.remove_edges_except(tk_graph, "REFERS_TO", ["e2", "e8"]) == 6
    assert _edge_keys(tk_graph) == ["e2", "e8", "x1"]


def test_the_keep_removals_write_in_chunks(
    tk_graph: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read in full, removed a few keys at a time: the same rows go as in one statement."""
    monkeypatch.setattr(chunks, "CHUNK", 2)
    assert normalize_edges.remove_edges_except(tk_graph, "REFERS_TO", ["e2", "e8"]) == 6
    assert _edge_keys(tk_graph) == ["e2", "e8"]
    assert normalize_edges.remove_nodes_except(tk_graph, "decisions", ["d1", "d7"]) == 5
    assert _node_keys(tk_graph, "decisions") == ["d1", "d7"]
    assert (
        semantic_edges.remove_edges_of_source_except(tk_graph, "REFERS_TO", "s", [])
        == 2
    )
    assert _edge_keys(tk_graph) == []


# ── gaps: laws ───────────────────────────────────────────────────────────────


@pytest.fixture()
def laws(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node(
                "r1",
                source="bwb",
                bwb_id="BWBR0000001",
                citation_title="Wet een",
                basis=[{"bwb_id": "bwbr0000009"}, {"bwb_id": "BWBR0000008"}, {}],
            ),
            _node(
                "r2",
                source="bwb",
                bwb_id="bwbr0000002",
                citation_title="",
                title="Wet twee",
                basis=[{"bwb_id": "BWBR0000008"}, {"bwb_id": None}, "x"],
            ),
            _node(
                "r3",
                source="bwb",
                bwb_id="BWBR0000003",
                stub=True,
                basis=[{"bwb_id": "BWBR0000009"}, {"bwb_id": "BWBR0000007"}],
            ),
            _node("r4", source="eurlex", basis=[{"bwb_id": "BWBR0000006"}]),
            _node("r5", source="bwb", bwb_id="BWBR0000005", basis="not a list"),
            _node("r6", source="bwb", bwb_id="BWBR0000004", display_name="Vier"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("a1", stub=True, bwb_id="BWBR0000020"),
            _node("a2", stub=True, bwb_id="BWBR0000020"),
            _node("a3", stub=True, bwb_id="BWBR0000010"),
            _node("a4", stub=True, bwb_id="BWBR0000030"),
            _node("a5", stub=True, bwb_id="BWBR0000030"),
            _node("a6", stub=False, bwb_id="BWBR0000040"),
            _node("a7", stub=True),
        ],
    )
    return store


def test_basis_bwb_ids_most_named_first_then_by_id(laws: GraphStore) -> None:
    # 9 named twice (once in lower case), 8 twice, 7 once; not the eurlex one
    assert list(gap_queries.basis_bwb_ids(laws)) == [
        "BWBR0000008",
        "BWBR0000009",
        "BWBR0000007",
    ]


def test_loaded_bwb_ids_upper_case_without_stubs(laws: GraphStore) -> None:
    assert set(gap_queries.loaded_bwb_ids(laws)) == {
        "BWBR0000001",
        "BWBR0000002",
        "BWBR0000005",
        "BWBR0000004",
    }


def test_stub_article_counts_most_first_then_by_id(laws: GraphStore) -> None:
    assert list(gap_queries.stub_article_counts(laws)) == [
        {"bwb_id": "BWBR0000020", "count": 2},
        {"bwb_id": "BWBR0000030", "count": 2},
        {"bwb_id": "BWBR0000010", "count": 1},
    ]


def test_instrument_titles_the_first_truthy_title(laws: GraphStore) -> None:
    assert list(gap_queries.instrument_titles(laws)) == [
        {"bwb_id": "BWBR0000001", "title": "Wet een"},
        {"bwb_id": "bwbr0000002", "title": "Wet twee"},  # "" is falsy
        {"bwb_id": "BWBR0000003", "title": None},
        {"bwb_id": "BWBR0000005", "title": None},
        {"bwb_id": "BWBR0000004", "title": "Vier"},
    ]


# ── gaps: judgments, EU acts, treaties ───────────────────────────────────────


def test_stub_judgment_eclis(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node("j1", stub=True, ecli="ECLI:NL:RBAMS:2020:2"),
            _node("j2", stub=True, ecli="ECLI:NL:HR:2020:1"),
            _node("j3", stub=False, ecli="ECLI:NL:HR:2020:3"),
            _node("j4", stub=True, ecli="ECLI:EU:C:2020:1"),
            _node("j5", stub=True, ecli="ECLI:CE:ECHR:2020:0102JUD000101"),
            _node("j6", stub=True, ecli="ECLI:CE:ECHR:2019:0102JUD000101"),
            _node("j7", stub=True),
        ],
    )
    assert list(gap_queries.stub_dutch_eclis(store)) == [
        "ECLI:NL:HR:2020:1",
        "ECLI:NL:RBAMS:2020:2",
    ]
    assert list(gap_queries.stub_echr_eclis(store)) == [
        "ECLI:CE:ECHR:2019:0102JUD000101",
        "ECLI:CE:ECHR:2020:0102JUD000101",
    ]


def test_unanswered_preliminary_rulings(store: GraphStore) -> None:
    ruling = {"type": PROCEDURE_PRELIMINARY_RULING}
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "p2",
                ecli="ECLI:NL:HR:2020:2",
                judgment_metadata=ruling,
                paragraphs=[{"n": 1}, {"n": 2}, {"n": 3}],
            ),
            _node("p1", ecli="ECLI:NL:HR:2020:1", judgment_metadata=ruling),
            _node(
                "p3",
                ecli="ECLI:NL:HR:2020:3",
                judgment_metadata=ruling,
                paragraphs=["a"],
            ),
            _node("other", ecli="ECLI:NL:HR:2020:4", judgment_metadata={"type": "x"}),
            _node("no-ecli", judgment_metadata=ruling),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("ans", "judgments/p3", "judgments/q", relation=RELATION_ANSWERS),
            _edge("ref", "judgments/p2", "judgments/q"),
        ]
    )
    assert list(gap_queries.unanswered_preliminary_rulings(store, paragraphs=2)) == [
        {"ecli": "ECLI:NL:HR:2020:1", "paragraphs": []},
        {"ecli": "ECLI:NL:HR:2020:2", "paragraphs": [{"n": 1}, {"n": 2}]},
    ]


def test_unretrieved_celex_refs(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("i1", celex_refs=["32016R0679", "32019L0001"]),
            _node("i2", implements_celex=["32019L0001", "32020L0002"], celex="X1"),
            _node("i3", celex_refs=["31995L0046"], implements_celex=["32016R0679"]),
            _node("i4", celex="X0"),
        ],
    )
    store.insert_raw_sources(
        [
            raw_source_doc(
                source=SOURCE_EURLEX, kind=RAW_KIND_EU_CELEX, external_id="32016r0679"
            ),
            raw_source_doc(
                source=SOURCE_EURLEX, kind="other", external_id="31995L0046"
            ),
        ]
    )
    assert list(gap_queries.unretrieved_celex_refs(store)) == [
        "31995L0046",
        "32019L0001",
        "32020L0002",
    ]
    assert list(gap_queries.known_celex_ids(store)) == ["X1", "X0"]


def test_stub_treaty_ids_in_key_order(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("t2", stub=True, kind="verdrag", external_id="V2"),
            _node("t1", stub=True, kind="multilateraalverdrag", external_id="V1"),
            _node("t3", stub=True, kind="bilateraalverdrag"),
            _node("t4", stub=False, kind="verdrag", external_id="V4"),
            _node("t5", stub=True, kind="wet", external_id="V5"),
        ],
    )
    assert list(gap_queries.stub_treaty_ids(store)) == ["V1", "V2", None]


# ── gaps: Kamerstukken and dossiers ──────────────────────────────────────────


def test_papers_with_dossier(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _tk(
                "k2",
                kind="Memorie van toelichting",
                title="MvT",
                dossier_number="36000",
                dossier_suffix="VI",
                sequence=3,
                date="2024-01-01",
            ),
            _tk(
                "k1",
                kind="Nota naar aanleiding van het verslag",
                title="",
                display_name="Nota",
                dossier_number="35000",
                sequence=7,
            ),
            _tk("k3", kind="Memorie van toelichting", dossier_number="1", sequence=1),
            _tk("k4", kind="Brief", dossier_number="1", sequence=2),
            _tk("k5", kind="Memorie van toelichting", dossier_number="1"),
            _node("k6", kind="Memorie van toelichting", dossier_number="1", sequence=1),
        ],
    )
    rows = list(gap_queries.papers_with_dossier(store, ["toelichting", "nota"]))
    assert rows == [
        {
            "key": "k1",
            "title": "Nota",
            "number": "35000",
            "suffix": None,
            "sequence": 7,
            "date": None,
        },
        {
            "key": "k2",
            "title": "MvT",
            "number": "36000",
            "suffix": "VI",
            "sequence": 3,
            "date": "2024-01-01",
        },
        {
            "key": "k3",
            "title": "k3",
            "number": "1",
            "suffix": None,
            "sequence": 1,
            "date": None,
        },
    ]
    assert list(rows[0]) == ["key", "title", "number", "suffix", "sequence", "date"]


def test_existing_raw_keys_and_retry_after(store: GraphStore) -> None:
    def doc(external_id: str, **meta: Any) -> dict[str, Any]:
        return raw_source_doc(
            source=SOURCE_TK, kind="k", external_id=external_id, meta=meta
        )

    store.insert_raw_sources(
        [
            doc("a", retry_after="2026-06-01"),
            doc("b", retry_after="2026-01-01"),
            doc("c"),
        ]
    )
    keys = [raw_key(SOURCE_TK, "k", x) for x in ("a", "b", "c", "d")]
    assert set(gap_queries.existing_raw_keys(store, keys)) == set(keys[:3])
    assert list(
        gap_queries.existing_raw_keys(store, keys, retry_after_iso="2026-03-01")
    ) == [keys[0]]


def test_dossier_gaps(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("d1", number="100", label="100"), _node("d2", label="200-VI")],
    )
    store.bulk_insert_or_update_nodes(
        "article_versions",
        [
            _node(
                "v1",
                origin_publication={"dossiers": ["300", "100", "abc"]},
                commencement_publication={"dossiers": ["250"]},
            ),
            _node("v2", origin_publication={"dossiers": ["300"]}),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments", [_node("i1", dossier_numbers=["0400", "300-A"])]
    )
    assert gap_queries.dossiers_named_by_publications(store) == ["0400", "250", "300"]
    assert gap_queries.dossiers_with_numbers(store, ["100", "300", "100"]) == {"100"}

    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _tk("p1", dossier_numbers=["200-VI", "500"]),
            _node("p2", dossier_numbers=["600"]),  # no TK paper
        ],
    )
    store.bulk_insert_or_update_nodes(
        "cases", [_node("c1", dossier_numbers=["500", "450-X"])]
    )
    assert gap_queries.dossiers_named_by_papers(store) == ["450-X", "500"]


def test_dossiers_missing_papers(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            # 36000 itself: 1, 2, 3 complete; 36000-XV: 1 and 3, not 2
            _tk("a1", dossier_number="36000", sequence=1),
            _tk("a2", dossier_number="36000", sequence=2),
            _tk("a3", dossier_number="36000", sequence=3),
            _tk("b1", dossier_number="36000", dossier_suffix="XV", sequence=1),
            _tk("b3", dossier_number="36000", dossier_suffix="XV", sequence=3),
            # 35000: 2 twice is one paper held, below 2
            _tk("c1", dossier_number="35000", sequence=2),
            _tk("c2", dossier_number="35000", sequence=2),
            _tk("d1", dossier_number="34000", sequence=1),
            _node("e1", dossier_number="33000", sequence=9),  # no TK paper
            _tk("f1", dossier_number="32000"),
        ],
    )
    assert gap_queries.dossiers_missing_papers(store) == ["35000", "36000"]


# ── what a retrieve chooses its work from ────────────────────────────────────


def test_holds_label(store: GraphStore) -> None:
    assert gap_queries.holds_label(store, "decisions", "EK") is False
    store.bulk_insert_or_update_nodes("decisions", [_tk("d1")])
    assert gap_queries.holds_label(store, "decisions", "EK") is False
    store.bulk_insert_or_update_nodes(
        "decisions", [{"_key": "d2", "type": "t", "labels": ["EK"], "props": {}}]
    )
    assert gap_queries.holds_label(store, "decisions", "EK") is True
    assert gap_queries.holds_label(store, "decisions", "TK") is True
