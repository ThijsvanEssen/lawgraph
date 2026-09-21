"""PART_OF always points child (article / annex) → instrument.

One contract, checked at both ends: every writer produces that direction, and
every AQL reader filters on it.
"""

from __future__ import annotations

from lawgraph.api.queries.relationships import _INSTRUMENT_FOR
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_PART_OF,
)
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.relations import BY_NAME
from lawgraph.db.store import edge_key
from lawgraph.pipelines.list_stats import _INSTRUMENTS_BODY
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.eurlex import EurlexNormalizePipeline
from lawgraph.pipelines.semantic.annex_links import AnnexLinksSemanticPipeline
from tests.conftest import _BaseFakeStore

INSTRUMENT = f"{COLLECTION_INSTRUMENTS}/BWBR0001854"
ARTICLE = f"{COLLECTION_ARTICLES}/BWBR0001854_1"


def _node(collection: str, node_type: NodeType, key: str) -> Node:
    return Node(
        collection=collection,
        type=node_type,
        key=key,
        props={},
        _skip_validation=True,
    )


# ── writers ──────────────────────────────────────────────────────────────────


def test_bwb_normalize_writes_article_to_instrument() -> None:
    store = _BaseFakeStore()
    instrument = _node(COLLECTION_INSTRUMENTS, NodeType.INSTRUMENT, "BWBR0001854")
    article = _node(COLLECTION_ARTICLES, NodeType.ARTICLE, "BWBR0001854_1")

    BWBNormalizePipeline(store=store).build_edges(
        [],
        {
            "instruments_by_bwb": {"BWBR0001854": instrument},
            "articles_by_bwb": {"BWBR0001854": [article]},
        },
    )

    (edge,) = store.edges.values()
    assert (edge["_from"], edge["_to"]) == (ARTICLE, INSTRUMENT)
    assert edge["_key"] == edge_key(ARTICLE, RELATION_PART_OF, INSTRUMENT)


def test_eu_normalize_writes_article_to_instrument() -> None:
    store = _BaseFakeStore()

    instrument = _node(COLLECTION_INSTRUMENTS, NodeType.INSTRUMENT, "32016R0679")
    article = _node(COLLECTION_ARTICLES, NodeType.ARTICLE, "32016R0679_1")

    EurlexNormalizePipeline(store=store).build_edges(
        [],
        {
            "instruments_by_celex": {"32016R0679": instrument},
            "articles_by_celex": {"32016R0679": [article]},
        },
    )

    (edge,) = store.edges.values()
    assert edge["_from"] == article.arango_id
    assert edge["_to"] == instrument.arango_id


def test_annex_edge_points_to_instrument() -> None:
    annex = _node("annexes", NodeType.ANNEX, "BWBR0001854_annex_I")

    edge = AnnexLinksSemanticPipeline(store=object())._instrument_edge(
        "BWBR0001854", annex
    )

    assert edge is not None
    assert edge["_from"] == annex.arango_id
    assert edge["_to"] == f"{COLLECTION_INSTRUMENTS}/{make_node_key('BWBR0001854')}"


def test_part_of_endpoints_match_the_catalogue() -> None:
    spec = BY_NAME[RELATION_PART_OF]
    assert COLLECTION_ARTICLES in spec.sources
    assert "annexes" in spec.sources
    assert COLLECTION_INSTRUMENTS in spec.targets
    assert COLLECTION_INSTRUMENTS not in spec.sources


# ── readers (AQL strings; a live ArangoDB is needed to execute them) ─────────


def test_list_stats_counts_edges_pointing_at_instrument() -> None:
    assert "e._to == inst._id" in _INSTRUMENTS_BODY
    assert "e._from == inst._id" not in _INSTRUMENTS_BODY


def test_relationship_query_looks_up_instrument_from_article() -> None:
    assert "pe._from == {target}" in _INSTRUMENT_FOR
    assert "DOCUMENT(pe._to)" in _INSTRUMENT_FOR
