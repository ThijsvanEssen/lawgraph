"""``semantic tk-amends``."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import EDGE_STATUS_VOORGESTELD, RELATION_AMENDS
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.relations import BY_NAME
from lawgraph.db.queries import removals
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.pipelines.semantic.tk import NamedActs
from lawgraph.pipelines.semantic.tk_amends import (
    TKAmendsSemanticPipeline,
    detect_amends_instrument,
)
from tests.fakes import InMemoryStore, calls_made, patch_alias_rows

# ---------------------------------------------------------------------------
# Pure detection helpers
# ---------------------------------------------------------------------------


SR = NamedActs({"Wetboek van Strafrecht": ("BWBR0001854", None)})


def test_detect_amends_instrument_matches_alias() -> None:
    hits = detect_amends_instrument(
        "Wijziging van het Wetboek van Strafrecht (aanpassing strafmaxima)", SR
    )
    assert len(hits) == 1
    bwb_id, celex, confidence = hits[0]
    assert bwb_id == "BWBR0001854"
    assert celex is None
    assert confidence == 0.85


def test_detect_amends_instrument_requires_wijziging_keyword() -> None:
    assert detect_amends_instrument("Debat over het Wetboek van Strafrecht", SR) == []


def test_detect_amends_instrument_none_title_returns_empty() -> None:
    assert detect_amends_instrument(None, SR) == []


def test_a_law_name_inside_a_longer_word_is_no_law_amended() -> None:
    erfgoedwet = NamedActs({"Erfgoedwet": ("BWBR0037521", None)})
    title = "Wijziging van de Erfgoedwetgeving in verband met de archieven"
    assert detect_amends_instrument(title, erfgoedwet) == []
    assert detect_amends_instrument("Wijziging van de Erfgoedwet", erfgoedwet) == [
        ("BWBR0037521", None, 0.85)
    ]


# ---------------------------------------------------------------------------
# Pipeline smoke tests
# ---------------------------------------------------------------------------


class _Store(InMemoryStore):
    """The instruments of the graph, the TK documents to read and the acts per dossier."""

    def __init__(self, pub_docs: list[dict[str, Any]], instruments: list[Node]) -> None:
        super().__init__({"instruments": [node.to_document() for node in instruments]})
        self.pub_docs = pub_docs
        self.acts: dict[str, set[str]] = {}


@pytest.fixture(autouse=True)
def _queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The instrument names and the TK documents come from the fake store; nothing is
    removed."""
    patch_alias_rows(monkeypatch)
    monkeypatch.setattr(
        semantic_tk,
        "tk_document_titles",
        lambda store, since_date: iter(list(store.pub_docs)),
    )
    monkeypatch.setattr(removals, "remove_edges_at", lambda *_a, **_k: [])
    monkeypatch.setattr(semantic_tk, "remove_own_act_edges", lambda *_a, **_k: 0)
    monkeypatch.setattr(semantic_tk, "acts_of_dossiers", lambda store: store.acts)


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


def _amends_store() -> _Store:
    return _Store(
        pub_docs=[_make_pub("pub1", "Wijziging van het Wetboek van Strafrecht")],
        instruments=[
            _make_instrument_node("BWBR0001854", title="Wetboek van Strafrecht")
        ],
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
    store.pub_docs = [
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
    store = _Store(
        pub_docs=[bill],
        instruments=[
            _make_instrument_node(
                "BWBR0020368", title="Wet op het financieel toezicht"
            ),
            own,
            eu,
        ],
    )
    # the act its dossier made, as the BWB names the dossier in its brondata
    store.acts = {"36931": {"instruments/bwbr0052854"}}

    TKAmendsSemanticPipeline(store=store).run()

    assert [e["_to"] for e in store.edges.values()] == ["instruments/bwbr0020368"]


def test_an_act_of_another_dossier_is_still_amended() -> None:
    bill = _make_pub("bill", "Wijziging van het Wetboek van Strafrecht")
    bill["props"]["dossier_numbers"] = ["36999"]
    store = _amends_store()
    store.pub_docs = [bill]
    store.acts = {"36001": {"instruments/bwbr0001854"}}

    TKAmendsSemanticPipeline(store=store).run()

    assert [e["_to"] for e in store.edges.values()] == ["instruments/bwbr0001854"]


def test_a_case_never_produces_an_edge() -> None:
    """Only a bill (Document) may propose a change; a Case is not an endpoint."""
    store = _amends_store()

    TKAmendsSemanticPipeline(store=store).run()

    assert not any(e["_from"].startswith("cases/") for e in store.edges.values())


def test_detect_amends_instrument_stays_fast_with_many_names() -> None:
    """Thousands of names must not mean thousands of steps per title: a title costs the
    same against one name as against twenty thousand and one."""
    title = "Wijziging van de WEGENWET in verband met het beheer van wegen"
    one = {"Wegenwet": ("BWBR0001948", None)}
    many = {f"Regeling nummer {n}": (f"BWBR{n:07d}", None) for n in range(20_000)}
    few_acts, many_acts = NamedActs(one), NamedActs({**many, **one})

    hits = [("BWBR0001948", None, 0.85)]
    assert detect_amends_instrument(title, few_acts) == hits
    assert detect_amends_instrument(title, many_acts) == hits
    assert calls_made(lambda: detect_amends_instrument(title, many_acts)) == calls_made(
        lambda: detect_amends_instrument(title, few_acts)
    )
