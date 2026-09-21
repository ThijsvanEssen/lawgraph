"""normalize bwb -> normalize bwb-history -> semantic bwb-amendments on one shared store.

Uses the real Grondwet fixture, so it proves the three pipelines agree on props and keys.
"""

from __future__ import annotations

from lawgraph.core.bwb_xml import publication_key
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline
from lawgraph.pipelines.normalize.bwb_history import BWBHistoryNormalizePipeline
from lawgraph.pipelines.semantic.bwb_amendments import BWBAmendmentsSemanticPipeline
from tests.normalize.test_bwb import GRONDWET, XML, _older, _record, _Store


class _GraphStore(_Store):
    """Also answers the amendments pipeline's three read queries."""

    def query(self, aql: str, bind_vars: dict | None = None, **kw):
        bind = bind_vars or {}
        if "origin_publication" in aql:
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
                for key, d in self.nodes.get("article_versions", {}).items()
                if d["props"].get("origin_publication") and d["props"].get("stam_id")
            ]
            return sorted(rows, key=lambda r: (r["bwb_id"], r["stam_id"]))
        if "a.props.stam_id IN @stam_ids" in aql:
            return [
                {
                    "key": k,
                    "bwb_id": d["props"]["bwb_id"],
                    "stam_id": d["props"].get("stam_id"),
                }
                for k, d in self.nodes.get("articles", {}).items()
                if d["props"].get("bwb_id") in bind["bwb_ids"]
                and d["props"].get("stam_id") in bind["stam_ids"]
            ]
        if "IS_ARRAY(i.props.dossier_numbers)" in aql:
            return [
                {"key": k, "dossiers": d["props"]["dossier_numbers"]}
                for k, d in self.nodes.get("instruments", {}).items()
                if d["props"].get("dossier_numbers")
            ]
        return super().query(aql, bind_vars, **kw)


def _edges(store: _GraphStore, relation: str) -> list[dict]:
    return [e for e in store.edges.values() if e["relation"] == relation]


def _run_all() -> _GraphStore:
    store = _GraphStore({"dossiers": {"35786": {"props": {}}, "34716": {"props": {}}}})
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


def test_amending_publication_amends_the_current_article() -> None:
    store = _run_all()

    art7 = f"articles/{make_node_key(GRONDWET, '7')}"
    stb_2019_33 = f"instruments/{publication_key('stb-2019-33')}"
    amends = [e for e in _edges(store, "AMENDS") if e["_to"] == art7]

    assert [e["_from"] for e in amends] == [stb_2019_33]
    assert amends[0]["meta"]["effect"] == "tekstplaatsing-wijziging"
    assert (
        amends[0]["meta"]["effective_date"] == "2002-03-21"
    )  # earliest version (fabricated old one)


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
    assert (
        f"instruments/{make_node_key(GRONDWET)}",
        f"dossiers/{make_node_key('35786')}",
    ) in legislated


def test_every_amendment_targets_an_existing_article() -> None:
    store = _run_all()

    for relation in ("AMENDS", "INTRODUCES", "REPEALS"):
        for edge in _edges(store, relation):
            collection, key = edge["_to"].split("/")
            assert key in store.nodes[collection], (relation, edge["_to"])
