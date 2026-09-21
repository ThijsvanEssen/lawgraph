"""``semantic tk-amends`` and ``semantic bwb-implements``."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import EDGE_STATUS_VOORGESTELD, RELATION_AMENDS
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.relations import BY_NAME
from lawgraph.pipelines.semantic.bwb_implements import BWBImplementsSemanticPipeline
from lawgraph.pipelines.semantic.tk_amends import (
    TKAmendsSemanticPipeline,
    detect_amends_instrument,
)
from tests.fakes import ExistingKeysFake

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


# ---------------------------------------------------------------------------
# Pipeline smoke tests
# ---------------------------------------------------------------------------


class _FakeStore(ExistingKeysFake):
    """Minimal store stub for tests of both pipelines."""

    def __init__(
        self,
        *,
        pub_docs: list[dict[str, Any]] | None = None,
        nodes: dict[tuple[str, str], Node] | None = None,
    ) -> None:
        self._pub_docs = pub_docs or []
        self._nodes = nodes or {}
        self.edges: dict[str, dict[str, Any]] = {}
        self._call = 0

    def query(
        self, aql: str, bind_vars: dict | None = None, **_kw: Any
    ) -> list[dict[str, Any]]:
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
        assert "raw_sources" not in aql  # no toestand XML is read here
        if "celex_refs" in aql:
            return [
                [node.props["bwb_id"], node.props["celex_refs"]]
                for (coll, _key), node in self._nodes.items()
                if coll == "instruments" and node.props.get("celex_refs")
            ]
        # TK documents collection query.
        if "documents" in aql:
            return list(self._pub_docs)
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
        "_id": f"documents/{key}",
        "type": NodeType.DOCUMENT.value,
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


def _amends_store() -> _FakeStore:
    inst_key = make_node_key("BWBR0001854")
    return _FakeStore(
        pub_docs=[_make_pub("pub1", "Wijziging van het Wetboek van Strafrecht")],
        nodes={
            ("instruments", inst_key): _make_instrument_node(
                "BWBR0001854", title="Wetboek van Strafrecht"
            ),
        },
    )


def test_pipeline_creates_a_proposed_amends_edge() -> None:
    store = _amends_store()

    result = TKAmendsSemanticPipeline(store=store).run()

    assert result.created == 1
    (edge,) = store.edges.values()
    assert edge["relation"] == RELATION_AMENDS
    assert edge["status"] == EDGE_STATUS_VOORGESTELD


def test_amends_endpoints_match_the_catalogue() -> None:
    store = _amends_store()

    TKAmendsSemanticPipeline(store=store).run()

    spec = BY_NAME[RELATION_AMENDS]
    for edge in store.edges.values():
        assert edge["_from"].split("/")[0] in spec.sources
        assert edge["_to"].split("/")[0] in spec.targets


def test_a_case_never_produces_an_edge() -> None:
    """Only a bill (Document) may propose a change; a Case is not an endpoint."""
    store = _amends_store()

    TKAmendsSemanticPipeline(store=store).run()

    assert not any(e["_from"].startswith("cases/") for e in store.edges.values())


def test_detect_amends_instrument_stays_fast_with_many_names() -> None:
    """Thousands of names must not mean thousands of compiled patterns per title."""
    import time

    aliases = {f"Regeling nummer {n}": (f"BWBR{n:07d}", None) for n in range(20_000)}
    aliases["Wegenwet"] = ("BWBR0001948", None)
    title = "Wijziging van de WEGENWET in verband met het beheer van wegen"

    started = time.perf_counter()
    hits = detect_amends_instrument(title, aliases)
    assert hits == [("BWBR0001948", None, 0.85)]
    assert time.perf_counter() - started < 0.5


def test_a_regulation_implements_the_eu_acts_normalize_found_in_it() -> None:
    """``normalize bwb`` keeps the CELEX numbers of a toestand on the regulation: the XML of
    every toestand (3 GB, two minutes) is not read again to find them."""
    law = Node(
        collection="instruments",
        type=NodeType.INSTRUMENT,
        key=make_node_key("BWBR0040940"),
        props={"bwb_id": "BWBR0040940", "celex_refs": ["32016R0679", "32099L9999"]},
        _skip_validation=True,
    )
    gdpr = Node(
        collection="instruments",
        type=NodeType.INSTRUMENT,
        key=make_node_key("32016R0679"),
        props={"celex": "32016R0679"},
        _skip_validation=True,
    )
    store = _FakeStore(
        nodes={("instruments", law.key): law, ("instruments", gdpr.key): gdpr}
    )
    result = BWBImplementsSemanticPipeline(store=store).run()

    assert result.created == 1  # the act that is not loaded gets no edge
    (edge,) = store.edges.values()
    assert edge["_from"] == law.arango_id and edge["_to"] == gdpr.arango_id
    assert edge["meta"] == {"celex": "32016R0679"}
