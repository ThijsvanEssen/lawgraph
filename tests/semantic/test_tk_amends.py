"""``semantic tk-amends``."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import EDGE_STATUS_VOORGESTELD, RELATION_AMENDS
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.relations import BY_NAME
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import tk as semantic_tk
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
    """Minimal store stub for the pipeline tests."""

    def __init__(
        self,
        *,
        pub_docs: list[dict[str, Any]] | None = None,
        nodes: dict[tuple[str, str], Node] | None = None,
    ) -> None:
        self._pub_docs = pub_docs or []
        self._nodes = nodes or {}
        self.edges: dict[str, dict[str, Any]] = {}

    def alias_rows(self) -> list[dict[str, Any]]:
        """The names and ids of the instruments, as the alias query returns them."""
        return [
            {
                "bwb_id": node.props.get("bwb_id"),
                "celex": node.props.get("celex"),
                "title": node.props.get("title"),
                "citation_title": node.props.get("citation_title"),
                "short_title": node.props.get("short_title"),
            }
            for (coll, _key), node in self._nodes.items()
            if coll == "instruments"
        ]

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


@pytest.fixture(autouse=True)
def _queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The instrument names and the TK documents come from the fake store; nothing is
    removed."""
    monkeypatch.setattr(
        semantic_bwb,
        "instrument_alias_rows",
        lambda store: iter(store.alias_rows()),
    )
    monkeypatch.setattr(
        semantic_tk,
        "tk_document_titles",
        lambda store, since_date: iter(list(store._pub_docs)),
    )
    monkeypatch.setattr(semantic_edges, "remove_edges_from", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        semantic_tk, "acts_of_dossiers", lambda store: getattr(store, "acts", {})
    )


def _make_pub(
    key: str,
    title: str,
    labels: list[str] | None = None,
    kind: str = "Voorstel van wet",
) -> dict[str, Any]:
    return {
        "_key": key,
        "_id": f"documents/{key}",
        "type": NodeType.DOCUMENT.value,
        "labels": labels or ["TK"],
        "props": {"title": title, "source": "tk", "kind": kind},
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


def test_a_motion_on_the_bill_amends_nothing() -> None:
    """A motie carries the title of the bill's dossier; only the bill and its amendementen
    change the law."""
    store = _amends_store()
    store._pub_docs = [
        _make_pub("motie", "Wijziging van het Wetboek van Strafrecht", kind="Motie"),
        _make_pub(
            "amendement",
            "Wijziging van het Wetboek van Strafrecht",
            kind="Amendement (gewijzigd/nader/vervangend)",
        ),
    ]

    TKAmendsSemanticPipeline(store=store).run()

    assert [e["_from"] for e in store.edges.values()] == ["documents/amendement"]


TITLE_36931 = (
    "Wijziging van de Wet op het financieel toezicht in verband met de implementatie van "
    "Verordening (EU) 2023/2869 betreffende het Europees centraal toegangspunt "
    "(Wet implementatie Europees centraal toegangspunt)"
)


def test_a_bill_amends_neither_the_eu_act_it_implements_nor_its_own_act() -> None:
    bill = _make_pub("bill", TITLE_36931)
    bill["props"]["dossier_numbers"] = ["36931"]
    own = _make_instrument_node(
        "BWBR0052854", title="Wet implementatie Europees centraal toegangspunt"
    )
    eu = Node(
        collection="instruments",
        type=NodeType.INSTRUMENT,
        key="32023r2869",
        props={"celex": "32023R2869", "title": "Verordening (EU) 2023/2869"},
        _skip_validation=True,
    )
    store = _FakeStore(
        pub_docs=[bill],
        nodes={
            ("instruments", "bwbr0020368"): _make_instrument_node(
                "BWBR0020368", title="Wet op het financieel toezicht"
            ),
            ("instruments", own.key): own,
            ("instruments", eu.key): eu,
        },
    )
    # the act its dossier made, as the BWB names the dossier in its brondata
    store.acts = {"36931": {"instruments/bwbr0052854"}}  # type: ignore[attr-defined]

    TKAmendsSemanticPipeline(store=store).run()

    assert [e["_to"] for e in store.edges.values()] == ["instruments/bwbr0020368"]


def test_an_act_of_another_dossier_is_still_amended() -> None:
    bill = _make_pub("bill", "Wijziging van het Wetboek van Strafrecht")
    bill["props"]["dossier_numbers"] = ["36999"]
    store = _amends_store()
    store._pub_docs = [bill]
    store.acts = {"36001": {"instruments/bwbr0001854"}}  # type: ignore[attr-defined]

    TKAmendsSemanticPipeline(store=store).run()

    assert [e["_to"] for e in store.edges.values()] == ["instruments/bwbr0001854"]


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
