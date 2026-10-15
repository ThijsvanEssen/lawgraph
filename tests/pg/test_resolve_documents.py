"""``resolve`` of a number with a numeric suffix on a real PostgreSQL: the subdossier when
there is one (``21501-31``), else a paper (``21501-12``: paper 12 of dossier 21501); the
answer, and reads that do not grow with the papers of the dossier. Dossier 21501 has some
thirty subdossiers (``21501-02``, ``21501-20``, …) with thousands of papers; reading each of
them, and its props with its text, took 30 s on the full graph."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import RELATION_PART_OF
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries.resolve import resolve
from tests.pg.plans import explain, plan_nodes, recorded

SUFFIXES = ("02", "20", "31")
DOCUMENTS = 60  # per subdossier


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


@pytest.fixture()
def seeded(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node(f"21501_{s}", "dossier", number="21501", suffix=s) for s in SUFFIXES]
        + [
            _node("35925", "dossier", number="35925", suffix=""),
            _node("36000", "dossier", number="36000", suffix=""),
        ],
    )
    papers = [
        _node(
            f"tk_21501_{s}_{n}",
            "document",
            source="tk",
            dossier_number="21501",
            dossier_suffix=s,
            sequence=n,
            display_name=f"Kamerstuk 21501-{s}, nr. {n}",
            text="De tekst van het stuk. " * 200,
        )
        for s in SUFFIXES
        for n in range(1, DOCUMENTS + 1)
    ]
    letters = [
        _node(
            f"ek_35925_{letter}",
            "document",
            source="eerstekamer",
            dossier_number="35925",
            number=letter,
            display_name=f"Kamerstuk I 35925, {letter}",
        )
        for letter in ("A", "B")
    ]
    other = [
        _node(
            "tk_36000_3",
            "document",
            source="tk",
            dossier_number="36000",
            sequence=3,
            display_name="Kamerstuk 36000, nr. 3",
        )
    ]
    store.bulk_insert_or_update_nodes("documents", papers + letters + other)
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                f"documents/{p['_key']}",
                f"dossiers/21501_{p['props']['dossier_suffix']}",
                RELATION_PART_OF,
            )
            for p in papers
        ]
        + [
            make_edge_doc(f"documents/{p['_key']}", "dossiers/35925", RELATION_PART_OF)
            for p in letters
        ]
        + [make_edge_doc("documents/tk_36000_3", "dossiers/36000", RELATION_PART_OF)]
    )
    store.vacuum_analyze()
    return store


def test_a_paper_of_a_number_with_subdossiers_is_each_paper_of_that_number(
    seeded: GraphStore,
) -> None:
    answer = resolve(seeded, "21501-12")

    keys = [m["key"] for m in [answer["match"], *answer["alternatives"]]]
    assert answer["kind"] == "document"
    assert keys == [f"tk_21501_{s}_12" for s in SUFFIXES]
    assert answer["confidence"] == 0.5  # three papers fit as well
    assert answer["match"]["display_name"] == "Kamerstuk 21501-02, nr. 12"
    assert resolve(seeded, "Kamerstuk I 35925, B")["match"]["key"] == "ek_35925_B"


def test_a_number_with_the_suffix_of_a_subdossier_is_that_subdossier(
    seeded: GraphStore,
) -> None:
    """``21501-31`` is the subdossier 21501-31 (as ``/dossiers/21501-31``), not paper 31 of
    each subdossier; ``36000-3``, where no subdossier 3 exists, stays paper 3."""
    answer = resolve(seeded, "21501-31")

    assert (answer["kind"], answer["match"]["key"]) == ("dossier", "21501_31")
    assert answer["confidence"] == 0.95
    assert [a["key"] for a in answer["alternatives"]] == ["21501_02", "21501_20"]

    paper = resolve(seeded, "36000-3")
    assert (paper["kind"], paper["match"]["key"]) == ("document", "tk_36000_3")


def test_a_paper_reads_its_candidates_not_every_paper_of_the_dossiers(
    seeded: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every statement of the resolve, run under ``EXPLAIN ANALYZE``: the rows it reads of
    the papers and of the edges stay at the papers with that number, not the 180 papers of
    the three subdossiers."""
    with monkeypatch.context() as patched:
        captured = recorded(seeded, patched)
        resolve(seeded, "21501-12")

    read = 0
    for call in captured:
        # planned as on the full graph: on these few rows a scan of a whole table is cheaper
        plan = explain(
            seeded,
            call.statement,
            call.params,
            disable=("seqscan", "hashjoin", "mergejoin"),
            analyze=True,
        )
        read += sum(
            (n["Actual Rows"] + n.get("Rows Removed by Filter", 0)) * n["Actual Loops"]
            for n in plan_nodes(plan)
            if n.get("Relation Name") in ("documents", "edges", "lg_document_light")
        )
    assert read < DOCUMENTS  # 8 here; 360 when every paper of the three is read
