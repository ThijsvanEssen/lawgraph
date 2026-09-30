"""normalize bwb -> normalize bwb-history -> semantic bwb-amendments on one shared store.

Uses the real Grondwet fixture, so it proves the three pipelines agree on props and keys.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.core.bwb_xml import publication_key
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import BWBHistoryNormalizePipeline
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from tests.conftest import remove_edges_from
from tests.normalize.test_bwb import (
    GRONDWET,
    XML,
    _older,
    _record,
    _Store,
    patch_store_queries,
)


@pytest.fixture(autouse=True)
def _graph_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of the normalize pipelines, and the amendments pipeline's three read
    queries and its removals, answered from the nodes of the shared store."""
    patch_store_queries(monkeypatch)

    def amending_article_versions(store: _Store) -> Iterator[dict[str, Any]]:
        rows = [
            {
                "key": key,
                "bwb_id": d["props"].get("bwb_id"),
                "stam_id": d["props"].get("stam_id"),
                "effect": d["props"].get("effect"),
                "valid_from": d["props"].get("valid_from"),
                "source_publication": d["props"].get("source_publication"),
                "origin": d["props"].get("origin_publication"),
                "commencement": d["props"].get("commencement_publication"),
            }
            for key, d in store.nodes.get("article_versions", {}).items()
            if d["props"].get("origin_publication") and d["props"].get("stam_id")
        ]
        return iter(sorted(rows, key=lambda r: (r["bwb_id"], r["stam_id"])))

    def articles_by_identity(
        store: _Store, bwb_ids: list[str], stam_ids: list[str]
    ) -> Iterator[dict[str, Any]]:
        return iter(
            {
                "key": k,
                "bwb_id": d["props"]["bwb_id"],
                "stam_id": d["props"].get("stam_id"),
            }
            for k, d in store.nodes.get("articles", {}).items()
            if d["props"].get("bwb_id") in bwb_ids
            and d["props"].get("stam_id") in stam_ids
        )

    def regulation_dossier_numbers(store: _Store) -> Iterator[dict[str, Any]]:
        return iter(
            {"key": k, "dossiers": d["props"].get("dossier_numbers") or []}
            for k, d in store.nodes.get("instruments", {}).items()
            if d["props"].get("bwb_id")
        )

    def remove_edges_from_ids(
        store: _Store, relation: str, source: str, ids: list[str], keep: dict
    ) -> int:
        bind = {"ids": ids, "relation": relation, "source": source, "keep": keep}
        return sum(remove_edges_from(store.edges, bind))

    def remove_edges_to_ids(
        store: _Store, relations: list[str], source: str, ids: list[str], keep: dict
    ) -> int:
        bind = {"ids": ids, "relations": relations, "source": source, "keep": keep}
        return sum(remove_edges_from(store.edges, bind))

    for module, name, answer in (
        (semantic_bwb, "amending_article_versions", amending_article_versions),
        (semantic_bwb, "articles_by_identity", articles_by_identity),
        (semantic_bwb, "regulation_dossier_numbers", regulation_dossier_numbers),
        (semantic_edges, "remove_edges_from", remove_edges_from_ids),
        (semantic_edges, "remove_edges_to", remove_edges_to_ids),
    ):
        monkeypatch.setattr(module, name, answer)


def _edges(store: _Store, relation: str) -> list[dict]:
    return [e for e in store.edges.values() if e["relation"] == relation]


def _run_all() -> _Store:
    store = _Store({"dossiers": {"35786": {"props": {}}, "34716": {"props": {}}}})
    records = [
        _record(_older(XML), "2002-03-21", "2023-02-21"),
        _record(XML, "2023-02-22", "9999-12-31"),
    ]
    current = BWBNormalizePipeline(store=store)
    current.build_edges([], current.normalize_nodes([records[1]], PipelineResult()))
    history = BWBHistoryNormalizePipeline(store=store)
    history.build_edges([], history.normalize_nodes(records, PipelineResult()))
    BWBAmendmentsSemanticPipeline(store=store).run()
    return store


def test_a_republication_amends_no_article() -> None:
    store = _run_all()

    # every version of artikel 7 is placed by the republication Stb. 2019, 33
    art7 = f"articles/{make_node_key(GRONDWET, '7')}"
    assert [e for e in _edges(store, "AMENDS") if e["_to"] == art7] == []
    assert f"instruments/{publication_key('stb-2019-33')}" not in {
        e["_from"] for e in store.edges.values()
    }


def test_new_and_repealed_articles_get_their_own_relations() -> None:
    store = _run_all()

    assert _edges(store, "INTRODUCES"), "an article with effect 'nieuw' is introduced"
    assert _edges(store, "REPEALS"), "articles with effect 'vervallen' are repealed"


def test_publication_instruments_carry_their_metadata_and_dossiers() -> None:
    store = _run_all()

    pub = store.nodes["instruments"][publication_key("stb-2019-33")]["props"]
    assert pub["display_name"] == "Stb. 2019, 33"
    assert (pub["publication_kind"], pub["publication_year"]) == ("Stb", 2019)
    legislated = {(e["_from"], e["_to"]) for e in _edges(store, "LEGISLATED_IN")}
    assert (
        f"instruments/{publication_key('stb-2018-493')}",
        f"dossiers/{make_node_key('34716')}",
    ) in legislated
    # the revision of 2022 is legislated in 35786, not the Grondwet (of 1840) itself
    assert (
        f"instruments/{publication_key('stb-2022-332')}",
        f"dossiers/{make_node_key('35786')}",
    ) in legislated
    assert not any(
        src == f"instruments/{make_node_key(GRONDWET)}" for src, _ in legislated
    )


def test_every_amendment_targets_an_existing_article() -> None:
    store = _run_all()

    for relation in ("AMENDS", "INTRODUCES", "REPEALS"):
        for edge in _edges(store, relation):
            collection, key = edge["_to"].split("/")
            assert key in store.nodes[collection], (relation, edge["_to"])
