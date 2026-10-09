"""Tests for the rechtspraak-citations semantic pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.identifiers import find_eclis
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.pipelines.semantic.rechtspraak_citations import (
    RechtspraakCitationsSemanticPipeline,
)
from tests.fakes import RawSourcesFake

# ---------------------------------------------------------------------------
# Pure detection helper
# ---------------------------------------------------------------------------


def test_detect_ecli_references_finds_single() -> None:
    hits = find_eclis("Zie ECLI:NL:HR:2020:1234 voor context.")
    assert hits == ["ECLI:NL:HR:2020:1234"]


def test_detect_ecli_references_deduplicates() -> None:
    text = "ECLI:NL:HR:2020:1234 en nogmaals ECLI:NL:HR:2020:1234"
    hits = find_eclis(text)
    assert hits == ["ECLI:NL:HR:2020:1234"]


def test_detect_ecli_references_multiple() -> None:
    text = "ECLI:NL:HR:2020:1234 en ECLI:NL:RBAMS:2021:5678"
    hits = find_eclis(text)
    assert len(hits) == 2


def test_detect_ecli_references_empty() -> None:
    assert find_eclis("") == []
    assert find_eclis(None) == []


# ---------------------------------------------------------------------------
# Pipeline smoke test
# ---------------------------------------------------------------------------


class _FakeStore(RawSourcesFake):
    def __init__(
        self,
        *,
        judgment_docs: list[dict[str, Any]],
        nodes: dict[tuple[str, str], Node] | None = None,
    ) -> None:
        self._judgment_docs = judgment_docs
        self._nodes = nodes or {}
        self.edges: dict[str, dict[str, Any]] = {}

    def payload_rows(self) -> list[dict[str, Any]]:
        """The stored judgments with their XML, as ``with_payloads`` passes them on."""
        return [
            {"ecli": d["props"]["ecli"], "payload_text": d["props"]["raw_xml"]}
            for d in self._judgment_docs
        ]

    def get_node(self, collection: str, key: str) -> Node | None:
        return self._nodes.get((collection, key))

    def insert_or_update_edge(self, doc: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        k = doc["_key"]
        created = k not in self.edges
        self.edges[k] = dict(doc)
        return self.edges[k], created

    def bulk_insert_or_update_edges(
        self, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        created = 0
        updated = 0
        for doc in docs:
            k = doc["_key"]
            was_created = k not in self.edges
            self.edges[k] = dict(doc)
            if was_created:
                created += 1
            else:
                updated += 1
        return created, updated

    def ensure_stub_node(
        self,
        collection: str,
        key: str,
        node_type: NodeType,
        props: dict[str, Any],
    ) -> Node:
        node = Node(
            collection=collection,
            type=node_type,
            key=key,
            props=props,
            _skip_validation=True,
        )
        self._nodes[(collection, key)] = node
        return node


@pytest.fixture()
def reads(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """The judgments come from the fake store; the ECLI lookup and the procedural edges
    find nothing, and nothing is removed. The *since_iso* of every read of the judgments."""
    since: list[str | None] = []

    def judgment_payload_refs(
        store: _FakeStore, *, since_iso: str | None, batch_size: int
    ) -> Iterator[dict[str, Any]]:
        since.append(since_iso)
        return iter(store.payload_rows())

    monkeypatch.setattr(raw_queries, "count_judgment_records", lambda store: None)
    monkeypatch.setattr(raw_queries, "judgment_payload_refs", judgment_payload_refs)
    monkeypatch.setattr(
        semantic_rechtspraak, "judgment_ids_by_ecli", lambda store, eclis: iter([])
    )
    monkeypatch.setattr(
        semantic_rechtspraak,
        "procedural_neighbours",
        lambda store, ids, relations: iter([]),
    )
    monkeypatch.setattr(semantic_edges, "remove_edges_from", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        semantic_rechtspraak, "remove_unreached_judgment_stubs", lambda store: 0
    )
    return since


def _make_judgment(key: str, ecli: str, text: str, related: str = "") -> dict[str, Any]:
    """A judgment whose XML holds *text* in its uitspraak and *related* in its metadata."""
    xml = (
        '<open-rechtspraak xmlns:dcterms="http://purl.org/dc/terms/"><rdf>'
        f"<dcterms:relation>{related}</dcterms:relation></rdf>"
        f"<uitspraak><para>{text}</para></uitspraak></open-rechtspraak>"
    )
    return {
        "_key": key,
        "_id": f"judgments/{key}",
        "type": NodeType.JUDGMENT.value,
        "labels": [],
        "props": {"ecli": ecli, "raw_xml": xml},
    }


def test_pipeline_creates_cites_judgment_edge(reads: list[str | None]) -> None:
    source_ecli = "ECLI:NL:HR:2020:1234"
    target_ecli = "ECLI:NL:HR:2019:9876"
    source_doc = _make_judgment(
        make_node_key(source_ecli),
        source_ecli,
        f"Zie het arrest {target_ecli} voor de onderbouwing.",
        # the metadata names the conclusion: procedure, not a citation
        related="ECLI:NL:PHR:2020:1",
    )
    target_key = make_node_key(target_ecli)
    target_node = Node(
        collection="judgments",
        type=NodeType.JUDGMENT,
        key=target_key,
        props={"ecli": target_ecli},
        _skip_validation=True,
    )
    store = _FakeStore(
        judgment_docs=[source_doc],
        nodes={("judgments", target_key): target_node},
    )
    pipeline = RechtspraakCitationsSemanticPipeline(store=store)
    result = pipeline.run()

    assert result.created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_REFERS_TO
    assert edge["_from"].startswith("judgments/")
    assert edge["_to"].startswith("judgments/")


def test_pipeline_skips_self_reference(reads: list[str | None]) -> None:
    ecli = "ECLI:NL:HR:2020:1234"
    doc = _make_judgment(
        make_node_key(ecli), ecli, f"Dit arrest ({ecli}) overweegt dat..."
    )
    store = _FakeStore(judgment_docs=[doc])
    pipeline = RechtspraakCitationsSemanticPipeline(store=store)
    result = pipeline.run()
    assert result.created == 0


def test_an_incremental_run_reads_the_judgments_fetched_since(
    reads: list[str | None],
) -> None:
    """The judgments read before have their edges; a cited judgment has the key of its stub."""
    import datetime as dt

    pipeline = RechtspraakCitationsSemanticPipeline(store=_FakeStore(judgment_docs=[]))
    pipeline.run(since=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc))
    assert reads == ["2025-01-01T00:00:00Z"]


def test_the_paragraphs_that_name_a_cited_judgment() -> None:
    from lawgraph.pipelines.semantic.rechtspraak_citations import paragraphs_citing

    found = paragraphs_citing(
        [
            {"number": "1.1", "text": "Zie ECLI:NL:HR:2015:1."},
            {"number": None, "text": "Ook ECLI:NL:HR:2015:1, zonder nummer."},
            {"number": "4.3", "text": "Zie ECLI:NL:HR:2015:1 en ECLI:NL:HR:2016:2."},
            {"number": "4.3", "text": "Nogmaals ECLI:NL:HR:2015:1."},
        ]
    )
    assert found == {
        "ECLI:NL:HR:2015:1": ["1.1", "4.3"],
        "ECLI:NL:HR:2016:2": ["4.3"],
    }
