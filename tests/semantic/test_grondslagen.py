"""Tests for the BWB grondslagen (BASED_ON) semantic pipeline, on real BWB XML."""

from __future__ import annotations

import pathlib
from typing import Any

from lawgraph.config.constants import RELATION_BASED_ON
from lawgraph.core.bwb_xml import instrument_props, parse_toestand
from lawgraph.core.models import make_node_key
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline
from tests.conftest import _BaseFakeStore

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
AMVB_XML = (FIXTURES / "bwb_amvb_toestand.xml").read_text()

AMVB_ID = "BWBR0001950"  # the fixture's regulation
BASIS_ID = "BWBR0001947"  # "Gelet op artikel 125 en 133 van de Ambtenarenwet 1929"


class _FakeStore(_BaseFakeStore):
    def __init__(
        self,
        raw_rows: list[dict[str, Any]],
        *,
        instruments: set[str] | None = None,
        articles: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.raw_rows = raw_rows
        self.instruments = instruments if instruments is not None else set()
        self.articles = articles if articles is not None else set()
        self.query_calls = 0
        self.existence_calls: list[str] = []

    def query(self, aql: str, bind_vars: dict | None = None, **_: Any):
        self.query_calls += 1
        assert (
            "raw_sources" not in aql
        )  # the basis is on the regulation, not parsed again
        known = [
            r for r in self.raw_rows if r["key"] in self.instruments and r["basis"]
        ]
        return iter(known)

    def existing_keys(self, collection: str, keys) -> set[str]:
        self.existence_calls.append(collection)
        known = {"instruments": self.instruments, "articles": self.articles}
        return set(keys) & known[collection]


def _run(store: _FakeStore):
    return BWBGrondslagenSemanticPipeline(store=store).run()


def _row(bwb_id: str = AMVB_ID, xml: str = AMVB_XML) -> dict[str, Any]:
    """What the query returns of the regulation ``normalize bwb`` makes of this XML."""
    props = instrument_props(parse_toestand(xml), bwb_id)
    return {"key": make_node_key(bwb_id), "bwb_id": bwb_id, "basis": props["basis"]}


def test_creates_based_on_edges_for_gelet_op_articles() -> None:
    store = _FakeStore(
        [_row()],
        instruments={make_node_key(AMVB_ID)},
        articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
    )

    result = _run(store)

    assert result.created == 2
    edges = list(store.edges.values())
    assert {e["relation"] for e in edges} == {RELATION_BASED_ON}
    assert {e["_from"] for e in edges} == {f"instruments/{make_node_key(AMVB_ID)}"}
    assert {e["_to"] for e in edges} == {
        f"articles/{make_node_key(BASIS_ID, '125')}",
        f"articles/{make_node_key(BASIS_ID, '133')}",
    }
    assert all(e["confidence"] == 1.0 and e["source"] for e in edges)
    assert all(e["meta"]["doc"].startswith("jci1.3:c:BWBR0001947") for e in edges)


def test_targets_missing_from_the_graph_are_skipped() -> None:
    store = _FakeStore(
        [_row()],
        instruments={make_node_key(AMVB_ID)},
        articles={make_node_key(BASIS_ID, "125")},  # 133 unknown
    )

    result = _run(store)

    assert result.created == 1
    assert result.skipped == 1
    (edge,) = store.edges.values()
    assert edge["_to"].endswith(make_node_key(BASIS_ID, "125"))


def test_unknown_regulation_gets_no_edges() -> None:
    store = _FakeStore(
        [_row()], instruments=set(), articles={make_node_key(BASIS_ID, "125")}
    )

    assert _run(store).created == 0
    assert not store.edges


def test_never_links_a_regulation_to_itself() -> None:
    # the same XML, but stored under the id of the regulation it is based on
    store = _FakeStore(
        [_row(bwb_id=BASIS_ID)],
        instruments={make_node_key(BASIS_ID)},
        articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
    )

    assert _run(store).created == 0
    assert not store.edges


def test_basis_without_article_number_makes_no_edge() -> None:
    xml = """<toestand bwb-id="BWBR0009999"><wetgeving><wet-besluit>
      <aanhef><considerans>
        <considerans.al>Gelet op de
          <extref doc="jci1.3:c:BWBR0001947" bwb-id="BWBR0001947">Ambtenarenwet</extref>;
        </considerans.al>
      </considerans></aanhef></wet-besluit></wetgeving></toestand>"""
    store = _FakeStore(
        [_row("BWBR0009999", xml)],
        instruments={make_node_key("BWBR0009999")},
        articles={make_node_key(BASIS_ID, "1")},
    )

    result = _run(store)

    assert result.created == 0
    assert not store.edges
    assert store.existence_calls == []  # nothing to check


def test_a_regulation_without_a_basis_is_not_even_read() -> None:
    """The query asks for the regulations that state one; XML that does not parse never
    became a regulation in ``normalize bwb``."""
    props = instrument_props(parse_toestand("<toestand><wetgeving/></toestand>"), "X")
    assert props["basis"] == []  # written, so a basis that was dropped does not stay
    store = _FakeStore(
        [{"key": "bwbr0000001", "bwb_id": "BWBR0000001", "basis": props["basis"]}],
        instruments={"bwbr0000001"},
    )

    result = _run(store)

    assert (result.created, result.skipped, result.errors) == (0, 0, [])
    assert store.existence_calls == []


def test_is_idempotent() -> None:
    store = _FakeStore(
        [_row()],
        instruments={make_node_key(AMVB_ID)},
        articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
    )

    first, second = _run(store), _run(store)

    assert (first.created, second.created, second.updated) == (2, 0, 2)
    assert len(store.edges) == 2


def test_store_calls_do_not_grow_with_the_number_of_regulations() -> None:
    def build(n: int) -> _FakeStore:
        ids = [f"BWBR{1000 + i:07d}" for i in range(n)]
        return _FakeStore(
            [_row(i, AMVB_XML) for i in ids],
            instruments={make_node_key(i) for i in ids},
            articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
        )

    small, large = build(2), build(40)  # 40 regulations fit in one chunk

    _run(small)
    _run(large)

    assert len(large.edges) == 80
    assert (large.query_calls, len(large.existence_calls)) == (
        small.query_calls,
        len(small.existence_calls),
    )
    assert large.existence_calls == ["articles"]
