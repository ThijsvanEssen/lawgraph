"""The pipeline that links the sections of a memorandum to the articles they explain."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import (
    RELATION_AMENDS,
    RELATION_ESTABLISHES,
    RELATION_EXPLAINS,
    RELATION_REPEALS,
)
from lawgraph.core.mvt_articles import CONFIDENCE_OF_MATCH, MATCH_BODY_NAMED_LAW
from lawgraph.core.relations import BY_NAME
from lawgraph.db.queries import removals
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.pipelines.semantic.tk_mvt import (
    DOSSIER_CONFIDENCE,
    SEMANTIC_SOURCE_SECTIONS,
)
from lawgraph.pipelines.semantic.tk_mvt_articles import (
    TKMvtArticlesSemanticPipeline,
)
from tests.fakes import InMemoryStore

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


class _Store(InMemoryStore):
    def __init__(
        self, rows: list[dict[str, Any]], amendments: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__()
        self.rows = rows
        self.amendments = amendments or []
        self.removals: list[tuple[list[str], dict[str, set[str]]]] = []


@pytest.fixture(autouse=True)
def _memoranda(monkeypatch: pytest.MonkeyPatch) -> None:
    """``memoranda_with_sections`` answers with the rows of the store; the removal of the
    section edges no longer found is recorded on it and removes none."""
    monkeypatch.setattr(
        semantic_tk,
        "memoranda_with_sections",
        lambda store, **_: iter(list(store.rows)),
    )
    monkeypatch.setattr(
        semantic_tk,
        "adopted_amendments_with_sections",
        lambda store, **_: iter(list(store.amendments)),
    )

    def removed(
        store: Any, end: str, relations: Any, ids: Any, keep: Any, *, source: str
    ) -> list:
        assert (end, relations, source) == (
            "from_id",
            [RELATION_EXPLAINS],
            SEMANTIC_SOURCE_SECTIONS,
        )
        store.removals.append((ids, keep))
        return []

    monkeypatch.setattr(removals, "remove_edges_at", removed)


def test_the_edge_of_an_article_lists_the_sections_that_explain_it() -> None:
    store = _Store([ROW])

    result = TKMvtArticlesSemanticPipeline(store=store).run()

    assert (result.created, result.skipped) == (1, 0)
    (edge,) = store.edges.values()
    assert edge["relation"] == RELATION_EXPLAINS
    assert edge["from_id"] == "documents/mvt-1"
    assert edge["to_id"] == "article_versions/bwbr0005068_stam2_v2"
    assert edge["source"] == SEMANTIC_SOURCE_SECTIONS
    assert edge["confidence"] == CONFIDENCE_OF_MATCH[MATCH_BODY_NAMED_LAW] < 1
    assert edge["meta"]["explanation"] == (
        "De tekst onder de kop 'Onderdeel A' noemt het artikel met zijn wet; het dossier "
        "wijzigt het artikel."
    )
    meta = edge["meta"]
    assert meta["section_anchor"] == "s-1"  # the first of two equally sure sections
    assert meta["match_type"] == "body_named_law" and meta["heading"] == "Onderdeel A"
    assert (meta["char_start"], meta["char_end"]) == (_ON_A, _ON_B - 1)
    assert [s["section_anchor"] for s in meta["sections"]] == ["s-1", "s-2"]
    assert TEXT[meta["char_start"] : meta["char_end"]].startswith("Onderdeel A\n")
    spec = BY_NAME[RELATION_EXPLAINS]
    assert edge["from_id"].split("/")[0] in spec.sources
    assert edge["to_id"].split("/")[0] in spec.targets


def test_a_second_run_writes_the_same_edge_again() -> None:
    store = _Store([ROW])
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
    store = _Store([silent])

    result = TKMvtArticlesSemanticPipeline(store=store).run()

    assert (result.created, result.skipped) == (0, 1)
    assert not store.edges


def test_a_row_the_query_did_not_shape_fails_the_run() -> None:
    """Nothing in reading a paper raises on its data: an error is a bug, not a paper."""
    broken = {**ROW, "document": "documents/mvt-2", "sections": [{"id": "s-0"}]}
    store = _Store([broken, ROW])

    with pytest.raises(KeyError):
        TKMvtArticlesSemanticPipeline(store=store).run()


def test_the_dossier_level_confidence_claims_less_than_any_section() -> None:
    assert DOSSIER_CONFIDENCE < min(CONFIDENCE_OF_MATCH.values())


def test_what_a_run_no_longer_finds_is_asked_for_the_memoranda_it_read() -> None:
    """A full run replaces its section edges: the removal names every memorandum read,
    with the keys of the edges it wrote."""
    store = _Store([ROW])

    TKMvtArticlesSemanticPipeline(store=store).run()

    ((ids, keep),) = store.removals
    assert ids == ["documents/mvt-1"]
    (edge,) = store.edges.values()
    assert keep == {"documents/mvt-1": {edge["key"]}}


_AMENDMENT_TEXT = (
    "AMENDEMENT VAN HET LID X\nDe ondergetekende stelt het volgende amendement voor:\n"
    "In artikel 2 van de Woningwet wordt «a» vervangen door: b.\n"
    "Toelichting\nDit amendement verduidelijkt artikel 2."
)
_TOELICHTING = _AMENDMENT_TEXT.index("Toelichting")
AMENDMENT_ROW = {
    **ROW,
    "document": "documents/amendement-1",
    "text": _AMENDMENT_TEXT,
    "sections": [
        {"id": "s-1", "heading": "Toelichting", "level": 1, "parent": None,
         "kind": "other", "number": None, "number_scheme": None, "article_refs": [],
         "law": None, "char_start": _TOELICHTING, "char_end": len(_AMENDMENT_TEXT)}
    ],
}  # fmt: skip


def test_an_adopted_amendment_explains_the_article_in_its_toelichting() -> None:
    store = _Store([], [AMENDMENT_ROW])

    TKMvtArticlesSemanticPipeline(store=store).run()

    (edge,) = store.edges.values()
    assert edge["from_id"] == "documents/amendement-1"
    assert edge["to_id"] == "article_versions/bwbr0005068_stam2_v2"
    assert edge["source"] == SEMANTIC_SOURCE_SECTIONS
    assert edge["meta"]["match_type"] == "amendment"
    assert edge["meta"]["heading"] == "Toelichting"
    # its edges are replaced like a memorandum's
    ((ids, _),) = store.removals
    assert ids == ["documents/amendement-1"]


# 36764: the bill is the Cyberbeveiligingswet, whose publication establishes it, and its
# article 99 changes the Telecommunicatiewet.
CBW = "BWBR0052872"
TW = "BWBR0009950"
_CBW_TEXT = (
    "Artikel 21 (zorgplicht)\n"
    "Artikel 21 Cbw ziet op de zorgplicht; artikel 22 regelt de meldplicht.\n"
    "Artikel 99 (wijziging Telecommunicatiewet)\n"
    "Artikel 11a.1 van de Telecommunicatiewet vervalt."
)
_CBW_99 = _CBW_TEXT.index("Artikel 99")


def _own_article(
    section_id: str, number: str, start: int, end: int, law: str | None
) -> dict[str, Any]:
    heading = _CBW_TEXT[start:end].split("\n", 1)[0]
    return {
        **_section(section_id, heading, start, end, None),
        "number": number,
        "number_scheme": "arabic",
        "article_refs": [{"number": number, "of": "self"}],
        "law": law,
    }


def _cbw_row(own: list[str]) -> dict[str, Any]:
    def change(bwb_id: str, number: str, relation: str) -> dict[str, Any]:
        key = f"{bwb_id.lower()}_{number}"
        return {
            "bwb_id": bwb_id,
            "number": number,
            "article": f"articles/{key}",
            "version": f"{key}_v1",
            "relation": relation,
        }

    return {
        "document": "documents/mvt-36764",
        "text": _CBW_TEXT,
        "sections": [
            _own_article("s-1", "21", 0, _CBW_99 - 1, None),
            _own_article(
                "s-2", "99", _CBW_99, len(_CBW_TEXT), "wijziging Telecommunicatiewet"
            ),
        ],
        "own": own,
        "changes": [
            change(CBW, "21", RELATION_ESTABLISHES),
            change(CBW, "22", RELATION_ESTABLISHES),
            change(CBW, "99", RELATION_ESTABLISHES),
            change(TW, "11a.1", RELATION_REPEALS),
        ],
        "laws": [
            {"bwb_id": CBW, "names": ["Cyberbeveiligingswet", None], "codes": [None]},
            {"bwb_id": TW, "names": ["Telecommunicatiewet", None], "codes": ["Tw"]},
        ],
    }


@pytest.mark.parametrize(
    "own",
    [[CBW], [], [CBW, TW]],
    ids=["law-names-its-dossier", "law-without-dossierref", "two-laws-name-it"],
)
def test_the_memorandum_of_a_law_its_publication_established(own: list[str]) -> None:
    """A heading "Artikel 21" is article 21 of the law the publication of the dossier
    established, whether or not the law names the dossier itself; the law it changes is
    explained as before, through the text under the heading."""
    store = _Store([_cbw_row(own)])

    TKMvtArticlesSemanticPipeline(store=store).run()

    edges = {edge["to_id"]: edge for edge in store.edges.values()}
    assert set(edges) == {
        "article_versions/bwbr0052872_21_v1",
        "article_versions/bwbr0052872_99_v1",
        "article_versions/bwbr0009950_11a.1_v1",
    }
    meta = edges["article_versions/bwbr0052872_21_v1"]["meta"]
    assert (meta["section_anchor"], meta["heading"]) == (
        "s-1",
        "Artikel 21 (zorgplicht)",
    )
    assert (meta["match_type"], meta["changed"]) == ("own_number", True)
    assert (meta["char_start"], meta["char_end"]) == (0, _CBW_99 - 1)
    assert meta["explanation"] == (
        "De kop 'Artikel 21 (zorgplicht)' is een artikel van de nieuwe wet; het dossier "
        "stelt het artikel vast."
    )
    # the heading of the article that changes another law is an article of the law too
    assert (
        edges["article_versions/bwbr0052872_99_v1"]["meta"]["section_anchor"] == "s-2"
    )
    tw = edges["article_versions/bwbr0009950_11a.1_v1"]["meta"]
    assert (tw["section_anchor"], tw["match_type"]) == ("s-2", "body_named_law")
    assert tw["explanation"].endswith("het dossier wijzigt het artikel.")
