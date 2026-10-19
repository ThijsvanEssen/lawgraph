"""Parts and references of an article, read from its props (no database)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.articles import (
    ArticleRelationshipWithType,
    ArticleSummaryDTO,
    ArticleVersionDTO,
    parts_from_props,
    references_from_props,
)
from lawgraph.core.qualifiers import Qualifier
from lawgraph.core.reference_targets import reference_targets
from lawgraph.db.queries.articles import ArticleCitationEntry, ArticleDetailData
from tests.api.stubs import stub_route

client = TestClient(app)

TEXT = "1. Aanhef:\na. eerste;\nb. tweede.\n2. Zie artikel 5, eerste lid, onder a."
PARTS: list[dict[str, Any]] = [
    {"id": "lid-1", "kind": "lid", "number": "1", "start": 3, "end": 32},
    {"id": "lid-1-aanhef", "kind": "aanhef", "number": None, "start": 3, "end": 10},
    {"id": "lid-1-onder-a", "kind": "onderdeel", "number": "a", "start": 14, "end": 21},
    {"id": "lid-2", "kind": "lid", "number": "2", "start": 36, "end": 71},
]
REFERENCES: list[dict[str, Any]] = [
    {
        "kind": "intref",
        "bwb_id": "BWBR0000001",
        "article": "5",
        "doc": "jci1.3:c:BWBR0000001&artikel=5",
        "text": "artikel 5, eerste lid, onder a",
        "start": 40,
        "end": 70,
        "leden": ["1"],
        "onderdelen": ["a"],
        "aanhef": False,
    },
    {
        "kind": "extref",
        "bwb_id": "BWBR0009999",
        "article": None,
        "doc": "jci1.3:c:BWBR0009999&hoofdstuk=2",
        "text": "hoofdstuk 2",
        "start": 1,
        "end": 2,
    },
    {
        "kind": "extref",
        "bwb_id": None,
        "article": None,
        "celex": "32016R0679",
        "doc": "32016R0679",
        "text": "verordening (EU) 2016/679",
        "start": 72,
        "end": 73,
    },
    {
        "kind": "intref",
        "bwb_id": "BWBR0000001",
        "article": None,
        "annex": "bwbr0000001_annex",
        "doc": "",
        "text": "bijlage",
        "start": 74,
        "end": 75,
    },
]
ARTICLE: dict[str, Any] = {
    "id": "articles/bwbr0000001_3",
    "key": "bwbr0000001_3",
    "props": {
        "bwb_id": "BWBR0000001",
        "article_number": "3",
        "text": TEXT,
        "parts": PARTS,
        "references": REFERENCES,
    },
}


def test_parts_carry_their_text_cut_from_the_article() -> None:
    parts = parts_from_props(ARTICLE["props"])

    assert [p.id for p in parts] == [p["id"] for p in PARTS]
    assert TEXT[3:10] == parts[1].text == "Aanhef:"
    assert (parts[2].number, parts[2].text) == ("a", "eerste;")
    assert parts[3].text.startswith("Zie artikel 5")


def test_parts_that_do_not_fit_the_text_are_left_out() -> None:
    props = {
        "text": "kort",
        "parts": [
            {"id": "lid-1", "kind": "lid", "number": "1", "start": 0, "end": 4},
            {"id": "lid-2", "kind": "lid", "number": "2", "start": 2, "end": 99},
            {"id": "lid-3", "kind": "lid", "number": "3", "start": 3, "end": 3},
            {"id": "lid-4", "start": "x", "end": None},
            "junk",
        ],
    }

    assert [p.id for p in parts_from_props(props)] == ["lid-1"]


def test_an_article_without_parts_or_text_has_an_empty_list() -> None:
    assert parts_from_props({}) == []
    assert parts_from_props({"text": "x", "parts": None}) == []
    assert parts_from_props({"parts": PARTS}) == []


def test_the_article_summary_and_a_version_have_parts() -> None:
    summary = ArticleSummaryDTO.from_document(ARTICLE)
    version = ArticleVersionDTO.from_document(
        {"key": "v1", "props": {"text": TEXT, "parts": PARTS}}, {}
    )

    assert [p.id for p in summary.parts] == [p["id"] for p in PARTS]
    assert version.parts == summary.parts


def test_references_come_in_text_order_with_what_they_name() -> None:
    first, second, eu, annex = references_from_props(
        ARTICLE["props"], {("articles", "bwbr0000001_5")}
    )

    assert (first.kind, first.article, first.start) == ("extref", None, 1)
    assert first.leden == [] and first.aanhef is False  # no qualifier fields stored
    assert (second.kind, second.leden, second.onderdelen) == ("intref", ["1"], ["a"])
    assert TEXT[second.start : second.end] == second.text
    assert eu.celex == "32016R0679" and annex.doc == ""


def test_a_reference_names_its_target_and_whether_the_data_holds_it() -> None:
    """The article a link names, else the regulation of a link to a chapter, the EU act
    of a CELEX link, the annex of a link to one; ``exists`` from the keys found."""
    found = {("articles", "bwbr0000001_5"), ("annexes", "bwbr0000001_annex")}
    targets = [
        ref.target.model_dump() if ref.target else None
        for ref in references_from_props(ARTICLE["props"], found)
    ]

    assert targets == [
        {
            "collection": "instruments",
            "key": "bwbr0009999",
            "id": "instruments/bwbr0009999",
            "exists": False,
        },
        {
            "collection": "articles",
            "key": "bwbr0000001_5",
            "id": "articles/bwbr0000001_5",
            "exists": True,
        },
        {
            "collection": "instruments",
            "key": "32016r0679",
            "id": "instruments/32016r0679",
            "exists": False,
        },
        {
            "collection": "annexes",
            "key": "bwbr0000001_annex",
            "id": "annexes/bwbr0000001_annex",
            "exists": True,
        },
    ]
    assert reference_targets(ARTICLE["props"]["references"]) == {
        "articles": {"bwbr0000001_5"},
        "instruments": {"bwbr0009999", "32016r0679"},
        "annexes": {"bwbr0000001_annex"},
    }


def test_the_article_detail_lists_its_references_and_the_qualifier_of_a_citation(
    monkeypatch,
) -> None:
    stub_route(
        monkeypatch,
        "articles",
        article_terms=([], {}, []),
        get_article_with_relations=lambda store, bwb_id, article_number: (
            ArticleDetailData(article=ARTICLE, instrument=None, metadata={})
        ),
    )
    target = {
        "id": "articles/bwbr0000001_5",
        "key": "bwbr0000001_5",
        "props": {"bwb_id": "BWBR0000001", "article_number": "5"},
    }
    stub_route(
        monkeypatch,
        "articles",
        get_article_citations=[
            ArticleCitationEntry(
                target=target,
                start=40,
                end=70,
                text="artikel 5, eerste lid, onder a",
                confidence=1.0,
                qualifier=Qualifier(leden=("1",), onderdelen=("a",)),
                reference_kind="intref",
            )
        ],
        get_article_relationship_data={},
        present_targets={("articles", "bwbr0000001_5")},
    )

    body = client.get("/api/articles/BWBR0000001/3").json()

    assert [p["id"] for p in body["article"]["parts"]] == [p["id"] for p in PARTS]
    assert len(body["references"]) == 4  # one resolves to no node in the graph
    assert body["references"][1]["leden"] == ["1"]
    assert [r["target"]["exists"] for r in body["references"]] == [
        False,
        True,
        False,
        False,
    ]
    (citation,) = body["citations"]
    assert citation["leden"] == ["1"] and citation["onderdelen"] == ["a"]
    assert citation["aanhef"] is False and citation["reference_kind"] == "intref"


def test_a_relationship_has_the_span_and_the_qualifier_of_its_edge() -> None:
    row = {
        "edge": {
            "key": "e1",
            "relation": "REFERS_TO",
            "meta": {
                "start": 40,
                "end": 70,
                "text": "artikel 5, tweede lid, aanhef",
                "reference_kind": "extref",
                "leden": ["2"],
                "onderdelen": [],
                "aanhef": True,
            },
        },
        "target": {"id": "articles/x", "key": "x", "props": {}},
        "instrument": None,
    }

    relation = ArticleRelationshipWithType.from_row(row)

    assert (relation.start, relation.end) == (40, 70)
    assert relation.text == "artikel 5, tweede lid, aanhef"
    assert (relation.leden, relation.aanhef, relation.reference_kind) == (
        ["2"],
        True,
        "extref",
    )


def test_a_relationship_of_an_edge_without_meta_is_empty_not_an_error() -> None:
    relation = ArticleRelationshipWithType.from_row(
        {
            "edge": {"key": "e1", "relation": "REFERS_TO"},
            "target": {"id": "articles/x", "key": "x", "props": {}},
        }
    )

    assert relation.start is None and relation.leden == [] and not relation.aanhef
