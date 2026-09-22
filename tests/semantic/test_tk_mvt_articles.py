"""The pipeline that links the sections of a memorandum to the articles they explain."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_AMENDS, RELATION_EXPLAINS
from lawgraph.core.mvt_articles import CONFIDENCE_OF_MATCH
from lawgraph.core.relations import BY_NAME
from lawgraph.pipelines.semantic.tk_mvt import (
    DOSSIER_CONFIDENCE,
    SEMANTIC_SOURCE_SECTIONS,
)
from lawgraph.pipelines.semantic.tk_mvt_articles import (
    TKMvtArticlesSemanticPipeline,
)
from tests.conftest import _BaseFakeStore

WONINGWET = "BWBR0005068"
TEXT = (
    "Artikel I\n"
    "Onderdeel A\nIn artikel 2 van de Woningwet is iets gewijzigd.\n"
    "Onderdeel B\nEen andere wijziging van artikel 2 van de Woningwet."
)


def _section(
    section_id: str, heading: str, start: int, end: int, parent: str | None
) -> dict[str, Any]:
    return {
        "id": section_id,
        "heading": heading,
        "level": 2 if parent else 1,
        "parent": parent,
        "kind": "onderdeel" if parent else "article",
        "number": None,
        "number_scheme": None,
        "article_refs": [],
        "law": None,
        "char_start": start,
        "char_end": end,
    }


_ON_A = TEXT.index("Onderdeel A")
_ON_B = TEXT.index("Onderdeel B")
SECTIONS = [
    _section("s-0", "Artikel I", 0, len(TEXT), None),
    _section("s-1", "Onderdeel A", _ON_A, _ON_B - 1, "s-0"),
    _section("s-2", "Onderdeel B", _ON_B, len(TEXT), "s-0"),
]

ROW = {
    "document": "documents/mvt-1",
    "text": TEXT,
    "sections": SECTIONS,
    "own": [],
    "changes": [
        {
            "bwb_id": WONINGWET,
            "number": "2",
            "article": "articles/bwbr0005068_2",
            "version": "bwbr0005068_stam2_v2",
            "relation": RELATION_AMENDS,
        }
    ],
    "laws": [{"bwb_id": WONINGWET, "names": ["Woningwet", None], "codes": [None]}],
}


class _FakeStore(_BaseFakeStore):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        super().__init__()
        self._rows = rows
        self.queries: list[str] = []

    def query(
        self, aql: str, bind_vars: dict | None = None, **_: Any
    ) -> list[dict[str, Any]]:
        self.queries.append(aql)
        return list(self._rows)

    def get_node(self, collection: str, key: str) -> dict | None:
        return None


def test_the_edge_of_an_article_lists_the_sections_that_explain_it() -> None:
    store = _FakeStore([ROW])

    result = TKMvtArticlesSemanticPipeline(store=store).run()

    assert (result.created, result.skipped) == (1, 0)
    (edge,) = store.edges.values()
    assert edge["relation"] == RELATION_EXPLAINS
    assert edge["_from"] == "documents/mvt-1"
    assert edge["_to"] == "article_versions/bwbr0005068_stam2_v2"
    assert edge["source"] == SEMANTIC_SOURCE_SECTIONS
    assert edge["confidence"] == 0.85
    meta = edge["meta"]
    assert meta["section_anchor"] == "s-1"  # the first of two equally sure sections
    assert meta["match_type"] == "body_named_law" and meta["heading"] == "Onderdeel A"
    assert (meta["char_start"], meta["char_end"]) == (_ON_A, _ON_B - 1)
    assert [s["section_anchor"] for s in meta["sections"]] == ["s-1", "s-2"]
    assert TEXT[meta["char_start"] : meta["char_end"]].startswith("Onderdeel A\n")
    spec = BY_NAME[RELATION_EXPLAINS]
    assert edge["_from"].split("/")[0] in spec.sources
    assert edge["_to"].split("/")[0] in spec.targets


def test_a_second_run_writes_the_same_edge_again() -> None:
    store = _FakeStore([ROW])
    TKMvtArticlesSemanticPipeline(store=store).run()
    first = {k: dict(v) for k, v in store.edges.items()}

    TKMvtArticlesSemanticPipeline(store=store).run()

    assert list(store.edges) == list(first)
    for key, edge in store.edges.items():
        assert edge["meta"] == first[key]["meta"]


def test_a_memorandum_that_names_no_article_is_skipped() -> None:
    text = "Artikel I\nGeen nummers."
    silent = {
        **ROW,
        "text": text,
        "sections": [_section("s-0", "Artikel I", 0, 22, None)],
    }
    store = _FakeStore([silent])

    result = TKMvtArticlesSemanticPipeline(store=store).run()

    assert (result.created, result.skipped) == (0, 1)
    assert not store.edges


def test_a_row_that_cannot_be_read_does_not_stop_the_others() -> None:
    broken = {**ROW, "document": "documents/mvt-2", "sections": [{"id": "s-0"}]}
    store = _FakeStore([broken, ROW])

    result = TKMvtArticlesSemanticPipeline(store=store).run()

    assert (result.created, result.skipped) == (1, 1)


def test_the_dossier_level_confidence_claims_less_than_any_section() -> None:
    assert DOSSIER_CONFIDENCE < min(CONFIDENCE_OF_MATCH.values())
