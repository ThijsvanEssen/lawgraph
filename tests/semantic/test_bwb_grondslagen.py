"""Tests for the BWB grondslagen (BASED_ON) semantic pipeline, on real BWB XML."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_BASED_ON
from lawgraph.core.bwb_xml import instrument_props, parse_toestand
from lawgraph.core.citations import LawDates
from lawgraph.core.models import make_node_key
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic.bwb_grondslagen import BWBGrondslagenSemanticPipeline
from tests.asserts import show_items
from tests.fakes import InMemoryStore
from tests.paths import fixture_text

pytestmark = pytest.mark.usefixtures("edge_removals")

AMVB_XML = fixture_text("bwb_amvb_toestand.xml")

AMVB_ID = "BWBR0001950"  # the fixture's regulation
BASIS_ID = "BWBR0001947"  # "Gelet op artikel 125 en 133 van de Ambtenarenwet 1929"


class _Store(InMemoryStore):
    """The regulations as their query returns them (``raw_rows``), the keys of the
    instruments and articles in the graph, the text of each article; ``reads`` and
    ``existence_calls`` count what the pipeline asked."""

    def __init__(
        self,
        raw_rows: list[dict[str, Any]],
        *,
        instruments: set[str] | None = None,
        articles: set[str] | None = None,
        texts: dict[str, str] | None = None,
        first: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.raw_rows = raw_rows
        self.first = first or {}
        self.instruments = instruments if instruments is not None else set()
        self.articles = articles if articles is not None else set()
        self.texts = texts or {}
        self.reads = 0
        self.existence_calls: list[str] = []


def _regulations_with_basis(store: _Store) -> Iterator[dict[str, Any]]:
    """The regulations in the graph that state a basis. It reads them from the
    regulation; the XML is not parsed again."""
    store.reads += 1
    return iter(
        r
        for r in store.raw_rows
        if r["key"] in store.instruments and (r["basis"] or r.get("basis_preamble"))
    )


def _basis_targets(store: _Store, keys: list[str]) -> Iterator[dict[str, Any]]:
    """The basis articles in the graph, with their text."""
    store.existence_calls.append("articles")
    return iter(
        {"key": k, "text": store.texts.get(k), "parts": None}
        for k in sorted(set(keys) & store.articles)
    )


def _articles_in_order(store: _Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """The articles of the laws, in the order of the law: here by number."""
    store.existence_calls.append("order")
    rows = [
        {"bwb_id": k.split("_")[0].upper(), "key": k}
        for k in store.articles
        if k.split("_")[0].upper() in set(bwb_ids)
    ]
    return iter(sorted(rows, key=lambda r: (r["bwb_id"], int(r["key"].split("_")[1]))))


def _first_versions(store: _Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """The start of the first toestand of the laws the graph has one of."""
    store.existence_calls.append("first")
    return iter(
        {"bwb_id": b, "first_from": store.first[b]} for b in bwb_ids if b in store.first
    )


@pytest.fixture(autouse=True)
def _regulations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(semantic_bwb, "regulations_with_basis", _regulations_with_basis)
    monkeypatch.setattr(semantic_bwb, "first_versions", _first_versions)
    monkeypatch.setattr(semantic_bwb, "basis_targets", _basis_targets)
    monkeypatch.setattr(semantic_bwb, "articles_in_order", _articles_in_order)


def _names(
    monkeypatch: pytest.MonkeyPatch,
    names: dict[str, str],
    dates: dict[str, LawDates] | None = None,
) -> None:
    """The laws the graph knows by name (title -> BWB id), no codes, and their *dates*."""
    pipeline = BWBGrondslagenSemanticPipeline
    monkeypatch.setattr(pipeline, "_load_code_choices", lambda self: ({}, {}))
    monkeypatch.setattr(
        pipeline,
        "_load_instrument_aliases",
        lambda self: {name: (law, None) for name, law in names.items()},
    )
    monkeypatch.setattr(pipeline, "_load_law_dates", lambda self: dates or {})


@pytest.fixture(autouse=True)
def _no_names(monkeypatch: pytest.MonkeyPatch) -> None:
    _names(monkeypatch, {})


def _run(store: _Store):
    return BWBGrondslagenSemanticPipeline(store=store).run()


def _row(bwb_id: str = AMVB_ID, xml: str = AMVB_XML) -> dict[str, Any]:
    """What the query returns of the regulation ``normalize bwb`` makes of this XML."""
    props = instrument_props(parse_toestand(xml), bwb_id)
    return {
        "key": make_node_key(bwb_id),
        "bwb_id": bwb_id,
        "basis": props["basis"],
        "basis_preamble": props["basis_preamble"],
    }


def test_creates_based_on_edges_for_gelet_op_articles() -> None:
    store = _Store(
        [_row()],
        instruments={make_node_key(AMVB_ID)},
        articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
    )

    result = _run(store)

    assert result.created == 2
    edges = list(store.edges.values())
    assert {e["relation"] for e in edges} == {RELATION_BASED_ON}
    assert {e["from_id"] for e in edges} == {f"instruments/{make_node_key(AMVB_ID)}"}
    assert {e["to_id"] for e in edges} == {
        f"articles/{make_node_key(BASIS_ID, '125')}",
        f"articles/{make_node_key(BASIS_ID, '133')}",
    }
    failing = [e for e in edges if not (e["confidence"] == 1.0 and e["source"])]
    assert not failing, show_items(failing)


def test_targets_missing_from_the_graph_are_skipped() -> None:
    store = _Store(
        [_row()],
        instruments={make_node_key(AMVB_ID)},
        articles={make_node_key(BASIS_ID, "125")},  # 133 unknown
    )

    result = _run(store)

    assert result.created == 1
    assert result.skipped == 1
    (edge,) = store.edges.values()
    assert edge["to_id"].endswith(make_node_key(BASIS_ID, "125"))


def test_unknown_regulation_gets_no_edges() -> None:
    store = _Store(
        [_row()], instruments=set(), articles={make_node_key(BASIS_ID, "125")}
    )

    assert _run(store).created == 0
    assert not store.edges


def test_never_links_a_regulation_to_itself() -> None:
    # the same XML, but stored under the id of the regulation it is based on
    store = _Store(
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
    store = _Store(
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
    store = _Store(
        [{"key": "bwbr0000001", "bwb_id": "BWBR0000001", "basis": props["basis"]}],
        instruments={"bwbr0000001"},
    )

    result = _run(store)

    assert (result.created, result.skipped, result.errors) == (0, 0, [])
    assert store.existence_calls == []


def test_is_idempotent() -> None:
    store = _Store(
        [_row()],
        instruments={make_node_key(AMVB_ID)},
        articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
    )

    first, second = _run(store), _run(store)

    assert (first.created, second.created, second.updated) == (2, 0, 2)
    assert len(store.edges) == 2


def test_store_calls_do_not_grow_with_the_number_of_regulations() -> None:
    def build(n: int) -> _Store:
        ids = [f"BWBR{1000 + i:07d}" for i in range(n)]
        return _Store(
            [_row(i, AMVB_XML) for i in ids],
            instruments={make_node_key(i) for i in ids},
            articles={make_node_key(BASIS_ID, "125"), make_node_key(BASIS_ID, "133")},
        )

    small, large = build(2), build(40)  # 40 regulations fit in one chunk

    _run(small)
    _run(large)

    assert len(large.edges) == 80
    assert (large.reads, len(large.existence_calls)) == (
        small.reads,
        len(small.existence_calls),
    )
    assert large.existence_calls == ["articles"]


def _gelet_op(refs: str) -> str:
    return f"""<toestand bwb-id="BWBR0009999"><wetgeving><wet-besluit>
      <aanhef><considerans><considerans.al>Gelet op {refs};</considerans.al>
      </considerans></aanhef></wet-besluit></wetgeving></toestand>"""


def _link(article: str, text: str) -> str:
    return (
        f'<extref doc="jci1.3:c:{BASIS_ID}&amp;artikel={article}" '
        f'bwb-id="{BASIS_ID}">{text}</extref>'
    )


def _edges_by_target(store: _Store) -> dict[str, dict[str, Any]]:
    return {e["to_id"].split("_")[-1]: e["meta"] for e in store.edges.values()}


def test_a_range_of_articles_links_every_article_in_it() -> None:
    """The BWB links "artikelen 6 tot en met 9" as one link to its first article."""
    xml = _gelet_op(
        f"de {_link('6', 'artikelen 6 tot en met 9')} en {_link('12', '12')}"
    )
    store = _Store(
        [_row("BWBR0009999", xml)],
        instruments={make_node_key("BWBR0009999")},
        # article 8 is not in the graph (repealed): the others of the range are linked
        articles={make_node_key(BASIS_ID, n) for n in ("5", "6", "7", "9", "10", "12")},
    )

    result = _run(store)

    by_target = _edges_by_target(store)
    assert sorted(by_target, key=int) == ["6", "7", "9", "12"]
    assert by_target["7"]["text"] == "6 tot en met 9"
    assert result.created == 4


def test_the_text_of_an_edge_has_no_list_word_nor_law() -> None:
    xml = _gelet_op(
        f"de {_link('3', 'artikelen 3')}, "
        f"{_link('16', '16, eerste en zevende lid')} en "
        f"{_link('107', '107 van de Cyberbeveiligingswet')}"
    )
    store = _Store(
        [_row("BWBR0009999", xml)],
        instruments={make_node_key("BWBR0009999")},
        articles={make_node_key(BASIS_ID, n) for n in ("3", "16", "107")},
    )

    _run(store)

    texts = {k: m["text"] for k, m in _edges_by_target(store).items()}
    assert texts == {"3": "3", "16": "16, eerste en zevende lid", "107": "107"}
    # one pass over the targets, no read of the order of a law without a range
    assert store.existence_calls == ["articles"]


def test_an_edge_says_whether_the_article_delegates() -> None:
    xml = _gelet_op(f"de {_link('3', 'artikelen 3')} en {_link('4', '4')}")
    store = _Store(
        [_row("BWBR0009999", xml)],
        instruments={make_node_key("BWBR0009999")},
        articles={make_node_key(BASIS_ID, n) for n in ("3", "4", "5")},
        texts={
            make_node_key(BASIS_ID, "3"): "Bij ministeriële regeling worden regels "
            "gesteld over de aanvraag.",
            make_node_key(BASIS_ID, "4"): "Het bestuursorgaan weegt de belangen af.",
        },
    )

    _run(store)

    kinds = {k: m["basis_kind"] for k, m in _edges_by_target(store).items()}
    assert kinds == {"3": "delegates", "4": "mentioned"}


ARBO_XML = """<toestand bwb-id="BWBR0008498"><wetgeving><wet-besluit>
  <aanhef><considerans>
    <considerans.al>Op de voordracht van de Staatssecretaris van Sociale Zaken;</considerans.al>
    <considerans.al bevat="grondslag">Gelet op de artikelen 1, 2, 4, 5, 6, 10, 20, 23a, 24, 36,
      en 41 van de Arbeidsomstandighedenwet en de
      <extref doc="jci1.3:c:BWBR0007952&amp;artikel=5" bwb-id="BWBR0007952">artikelen 5 en 8 van
      de Winkeltijdenwet</extref>;</considerans.al>
  </considerans></aanhef></wet-besluit></wetgeving></toestand>"""
ARBOWET_ID = "BWBR0010346"
WINKELTIJDEN_ID = "BWBR0007952"


def test_a_law_named_without_a_link_is_read_from_the_preamble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Arbeidsomstandighedenbesluit links only the Winkeltijdenwet; the Arbowet it is
    mainly made under stands in words ("..., en 41 van de Arbeidsomstandighedenwet")."""
    _names(
        monkeypatch,
        {"Arbeidsomstandighedenwet": ARBOWET_ID, "Winkeltijdenwet": WINKELTIJDEN_ID},
    )
    arbowet = {make_node_key(ARBOWET_ID, n) for n in ("1", "5", "23a", "41", "99")}
    store = _Store(
        [_row("BWBR0008498", ARBO_XML)],
        instruments={make_node_key("BWBR0008498")},
        articles=arbowet | {make_node_key(WINKELTIJDEN_ID, "8")},
    )

    _run(store)

    targets = {e["to_id"].removeprefix("articles/") for e in store.edges.values()}
    assert targets == {
        make_node_key(ARBOWET_ID, n) for n in ("1", "5", "23a", "41")
    } | {make_node_key(WINKELTIJDEN_ID, "8")}
    by_target = {e["to_id"].removeprefix("articles/"): e for e in store.edges.values()}
    assert by_target[make_node_key(ARBOWET_ID, "41")]["confidence"] < 1.0


GRONDWET_ID = "BWBR0001840"
KB_ID = "BWBR0002335"  # Besluit regeling overdracht zorg voor reiswezen (1959)
AMBTENARENWET_125 = _link("125", "artikel 125 van de Ambtenarenwet")
KB_XML = f"""<toestand bwb-id="{KB_ID}"><wetgeving><wet-besluit><aanhef><considerans>
  <considerans.al>Gelet op artikel 86 van de Grondwet en {AMBTENARENWET_125};
  </considerans.al></considerans></aanhef></wet-besluit></wetgeving></toestand>"""


def _grondwet_of(monkeypatch: pytest.MonkeyPatch, signed: str) -> _Store:
    """The KB signed on *signed*; the Grondwet known by name, its first toestand in the BWB
    of 2002 (the source has no older one)."""
    _names(
        monkeypatch,
        {"Grondwet": GRONDWET_ID},
        {KB_ID: LawDates(signed, signed), GRONDWET_ID: LawDates("1815-08-24", None)},
    )
    return _Store(
        [_row(KB_ID, KB_XML)],
        instruments={make_node_key(KB_ID)},
        articles={make_node_key(GRONDWET_ID, "86"), make_node_key(BASIS_ID, "125")},
        first={GRONDWET_ID: "2002-03-21", BASIS_ID: "2002-01-01"},
    )


def test_a_reference_in_words_older_than_the_law_in_the_bwb_is_a_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Article 86 of the Grondwet of 1959 is not the article 86 of now: no edge to it, a
    gap on the KB. The link to the Ambtenarenwet is the source's own and stays."""
    store = _grondwet_of(monkeypatch, "1959-12-15")

    result = _run(store)

    targets = {e["to_id"].removeprefix("articles/") for e in store.edges.values()}
    assert targets == {make_node_key(BASIS_ID, "125")}
    kb = store.nodes["instruments"][make_node_key(KB_ID)]["props"]
    assert kb["basis_unresolved"] == [
        {
            "bwb_id": GRONDWET_ID,
            "article": "86",
            "text": "86",
            "reason": "before_first_version",
        }
    ]
    assert result.updated == 1

    # written once: a second run finds it as it was and writes no node
    store.raw_rows = [
        {**_row(KB_ID, KB_XML), "basis_unresolved": kb["basis_unresolved"]}
    ]
    before = store.nodes["instruments"][make_node_key(KB_ID)]
    store.nodes["instruments"].clear()
    _run(store)
    # no node written: had it been, the node would be back
    assert store.nodes["instruments"] == {}
    assert before["props"]["basis_unresolved"] == kb["basis_unresolved"]


def test_a_reference_in_words_of_a_regulation_the_bwb_has_the_law_for_is_linked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _grondwet_of(monkeypatch, "2003-01-01")

    _run(store)

    targets = {e["to_id"].removeprefix("articles/") for e in store.edges.values()}
    assert make_node_key(GRONDWET_ID, "86") in targets
    assert store.nodes.get("instruments") is None  # no gap, nothing written


def test_a_gap_that_resolved_is_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _grondwet_of(monkeypatch, "2003-01-01")
    store.raw_rows = [{**_row(KB_ID, KB_XML), "basis_unresolved": [{"article": "86"}]}]
    store.nodes.setdefault("instruments", {})[make_node_key(KB_ID)] = {
        "_key": make_node_key(KB_ID),
        "props": {"basis_unresolved": [{"article": "86"}]},
    }

    _run(store)

    kb = store.nodes["instruments"][make_node_key(KB_ID)]["props"]
    assert kb["basis_unresolved"] is None
