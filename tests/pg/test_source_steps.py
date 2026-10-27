"""``semantic graph-steps`` on a real graph: one row per pair of sources, through the nodes they
share up to the cap, without the ``PART_OF`` of a law, weighed by Adamic-Adar."""

from __future__ import annotations

import math
from typing import Any

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries.source_steps import (
    DIRECT_WEIGHT,
    THROUGH_CAP,
    build_source_steps,
    steps_built,
)

LAW, OTHER_LAW = f"{COLLECTION_INSTRUMENTS}/zz", f"{COLLECTION_INSTRUMENTS}/aa"
ART_1, ART_2 = f"{COLLECTION_ARTICLES}/zz_1", f"{COLLECTION_ARTICLES}/zz_2"
PAPER = f"{COLLECTION_DOCUMENTS}/p1"
RULING = f"{COLLECTION_JUDGMENTS}/j1"


def _edge(source: str, target: str, relation: str = RELATION_REFERS_TO) -> Any:
    return make_edge_doc(source, target, relation, source="test")


def _steps(store: GraphStore) -> dict[tuple[str, str], tuple[int, bool, float]]:
    rows = store.query("SELECT a, b, ways, direct, weight FROM source_steps")
    return {(r["a"], r["b"]): (r["ways"], r["direct"], r["weight"]) for r in rows}


def test_a_pair_is_one_row_in_byte_order_weighed_by_what_they_share(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_edges(
        [
            # the paper names both laws: a node of two sources
            _edge(PAPER, LAW),
            _edge(PAPER, OTHER_LAW),
            # the judgment cites both and the article: a node of three
            _edge(RULING, LAW),
            _edge(RULING, OTHER_LAW),
            _edge(RULING, ART_1),
            # an edge between two sources, both ways
            _edge(LAW, OTHER_LAW),
            _edge(OTHER_LAW, LAW),
        ]
    )
    assert not steps_built(store)
    assert build_source_steps(store) == 3
    assert steps_built(store)

    found = _steps(store)
    # "articles/…" < "instruments/aa" < "instruments/zz", by byte
    ways, direct, weight = found[(OTHER_LAW, LAW)]
    assert (ways, direct) == (2, True)
    assert weight == pytest.approx(1 / math.log(2) + 1 / math.log(3) + DIRECT_WEIGHT)
    assert found[(ART_1, OTHER_LAW)][:2] == (1, False)
    assert found[(ART_1, LAW)][2] == pytest.approx(1 / math.log(3))
    nodes = {
        r["id"]: r["sources"]
        for r in store.query("SELECT id, sources FROM source_step_nodes")
    }
    # every node of two sources or more; the laws touch one source each
    assert nodes == {PAPER: 2, RULING: 3}


def test_a_node_of_more_sources_than_the_cap_joins_none(store: GraphStore) -> None:
    many = [f"{COLLECTION_ARTICLES}/m_{i:02}" for i in range(THROUGH_CAP + 1)]
    store.bulk_insert_or_update_edges(
        [_edge(PAPER, a) for a in many] + [_edge(RULING, a) for a in many[:THROUGH_CAP]]
    )
    build_source_steps(store)

    found = _steps(store)
    # the judgment touches 50: each two of them one step apart through it alone
    assert len(found) == THROUGH_CAP * (THROUGH_CAP - 1) // 2
    assert {ways for ways, _, _ in found.values()} == {1}
    nodes = {
        r["id"]: r["sources"]
        for r in store.query("SELECT id, sources FROM source_step_nodes")
    }
    assert nodes == {PAPER: THROUGH_CAP + 1, RULING: THROUGH_CAP}


def test_the_part_of_a_law_is_no_step_and_joins_none(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges(
        [
            _edge(ART_1, LAW, RELATION_PART_OF),
            _edge(ART_2, LAW, RELATION_PART_OF),
            _edge(ART_1, ART_2),
        ]
    )
    build_source_steps(store)

    # the law shares nothing with its articles, nor are they a step apart through it
    ((pair, (ways, direct, weight)),) = _steps(store).items()
    assert (pair, ways, direct) == ((ART_1, ART_2), 0, True)
    assert weight == pytest.approx(DIRECT_WEIGHT)


def test_a_build_replaces_the_steps_whole(store: GraphStore) -> None:
    store.bulk_insert_or_update_edges([_edge(LAW, OTHER_LAW)])
    build_source_steps(store)
    store.execute("DELETE FROM edges")
    store.bulk_insert_or_update_edges([_edge(ART_1, ART_2)])

    assert build_source_steps(store) == 1
    assert list(_steps(store)) == [(ART_1, ART_2)]
    indexes = sorted(
        store.query(
            "SELECT indexname FROM pg_indexes"
            " WHERE tablename IN ('source_steps', 'source_step_nodes')"
        )
    )
    assert indexes == ["source_step_nodes_pkey", "source_steps_a", "source_steps_b"]


def test_the_step_builds_them(store: GraphStore) -> None:
    from lawgraph.pipelines.semantic.graph_steps import GraphStepsSemanticPipeline

    store.bulk_insert_or_update_edges([_edge(LAW, OTHER_LAW)])
    assert GraphStepsSemanticPipeline(store).run().updated == 1
