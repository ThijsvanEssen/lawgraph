"""Tests for the instrument-relations semantic pipeline."""

from __future__ import annotations

from typing import Any

from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.instrument_relations import (
    InstrumentRelationsPipeline,
    detect_amends_instrument,
    detect_celex_references,
)

# ---------------------------------------------------------------------------
# Pure detection helpers
# ---------------------------------------------------------------------------


def test_detect_amends_instrument_matches_alias() -> None:
    aliases = {"Wetboek van Strafrecht": ("BWBR0001854", None)}
    hits = detect_amends_instrument(
        "Wijziging van het Wetboek van Strafrecht (aanpassing strafmaxima)",
        aliases,
    )
    assert len(hits) == 1
    bwb_id, celex, confidence = hits[0]
    assert bwb_id == "BWBR0001854"
    assert celex is None
    assert confidence == 0.85


def test_detect_amends_instrument_requires_wijziging_keyword() -> None:
    aliases = {"Wetboek van Strafrecht": ("BWBR0001854", None)}
    hits = detect_amends_instrument("Debat over het Wetboek van Strafrecht", aliases)
    assert hits == []


def test_detect_amends_instrument_none_title_returns_empty() -> None:
    assert detect_amends_instrument(None, {"Sr": ("BWBR0001854", None)}) == []


def test_detect_celex_references_finds_valid_celex() -> None:
    hits = detect_celex_references("De wet implementeert 32019L1158 en 32009L0028.")
    assert "32019L1158" in hits
    assert "32009L0028" in hits


def test_detect_celex_references_returns_empty_for_blank() -> None:
    assert detect_celex_references("") == []
    assert detect_celex_references(None) == []


# ---------------------------------------------------------------------------
# Pipeline smoke tests
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal store stub for instrument-relations pipeline tests."""

    def __init__(
        self,
        *,
        pub_docs: list[dict[str, Any]] | None = None,
        proc_docs: list[dict[str, Any]] | None = None,
        nodes: dict[tuple[str, str], Node] | None = None,
    ) -> None:
        self._pub_docs = pub_docs or []
        self._proc_docs = proc_docs or []
        self._nodes = nodes or {}
        self.edges: dict[str, dict[str, Any]] = {}
        self._call = 0

    def query(self, aql: str, bind_vars: dict | None = None) -> list[dict[str, Any]]:
        # Instrument index query — return instrument nodes so alias detection works.
        if "FOR inst IN instruments" in aql:
            rows = []
            for (coll, _key), node in self._nodes.items():
                if coll != "instruments":
                    continue
                rows.append(
                    {
                        "bwb_id": node.props.get("bwb_id"),
                        "celex": node.props.get("celex"),
                        "title": node.props.get("title"),
                        "citation_title": node.props.get("citation_title"),
                        "short_title": node.props.get("short_title"),
                    }
                )
            return rows
        # BWB raw-text query.
        if "raw_sources" in aql:
            return []
        # TK publications collection query.
        if "publications" in aql:
            return list(self._pub_docs)
        # TK procedures collection query.
        if "procedures" in aql:
            return list(self._proc_docs)
        return []

    def get_node(self, collection: str, key: str) -> Node | None:
        return self._nodes.get((collection, key))

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created

    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        created, updated = 0, 0
        for doc in docs:
            was_new = doc["_key"] not in self.edges
            self.edges[doc["_key"]] = dict(doc)
            if was_new:
                created += 1
            else:
                updated += 1
        return created, updated


def _make_pub(key: str, title: str, labels: list[str] | None = None) -> dict[str, Any]:
    return {
        "_key": key,
        "_id": f"publications/{key}",
        "type": NodeType.PUBLICATION.value,
        "labels": labels or ["TK"],
        "props": {"title": title, "source": "tk"},
    }


def _make_instrument_node(bwb_id: str, title: str | None = None) -> Node:
    key = make_node_key(bwb_id)
    props: dict[str, Any] = {"bwb_id": bwb_id}
    if title:
        props["title"] = title
    return Node(
        collection="instruments",
        type=NodeType.INSTRUMENT,
        key=key,
        props=props,
        _skip_validation=True,
    )


def test_pipeline_creates_amends_instrument_edge() -> None:
    inst_key = make_node_key("BWBR0001854")
    pub_doc = _make_pub("pub1", "Wijziging van het Wetboek van Strafrecht")
    store = _FakeStore(
        pub_docs=[pub_doc],
        nodes={
            ("instruments", inst_key): _make_instrument_node(
                "BWBR0001854", title="Wetboek van Strafrecht"
            ),
        },
    )
    pipeline = InstrumentRelationsPipeline(store=store)
    result = pipeline.run()

    assert result.created >= 1
    relations = {e["relation"] for e in store.edges.values()}
    assert "AMENDS_INSTRUMENT" in relations


def test_pipeline_creates_discusses_edge_for_procedure() -> None:
    inst_key = make_node_key("BWBR0001854")
    proc_doc = {
        "_key": "proc1",
        "_id": "procedures/proc1",
        "type": NodeType.PROCEDURE.value,
        "labels": ["TK"],
        "props": {"title": "Debat Wetboek van Strafrecht aanpassingen"},
    }
    store = _FakeStore(
        proc_docs=[proc_doc],
        nodes={
            ("instruments", inst_key): _make_instrument_node(
                "BWBR0001854", title="Wetboek van Strafrecht"
            ),
        },
    )
    pipeline = InstrumentRelationsPipeline(store=store)
    result = pipeline.run()

    assert result.created >= 1
    relations = {e["relation"] for e in store.edges.values()}
    assert "DISCUSSES" in relations
