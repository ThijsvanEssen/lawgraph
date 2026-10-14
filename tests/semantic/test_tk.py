"""Tests for the TK article semantic pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.models import NodeType, make_node_key
from lawgraph.db.queries import removals
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.pipelines.semantic.tk import (
    TKSemanticPipeline,
    detect_tk_citations,
)
from tests.fakes import InMemoryStore, patch_alias_rows


def _store(
    documents: list[dict[str, Any]],
    instruments: dict[str, dict[str, Any]],
    articles: dict[str, dict[str, Any]],
) -> InMemoryStore:
    return InMemoryStore(
        {
            "documents": documents,
            "instruments": instruments.values(),
            "articles": articles.values(),
        }
    )


@pytest.fixture(autouse=True)
def _tk_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of the pipeline, answered from the documents and instruments of the
    fake store; no law lists its articles, so a cited article resolves by its node."""

    def tk_documents(
        store: InMemoryStore,
        ids: list[str] | None,
        *,
        after: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        assert (ids, after, limit) == (None, None, None)  # a full run: every document
        return iter(store.nodes["documents"].values())

    monkeypatch.setattr(semantic_tk, "tk_documents", tk_documents)
    monkeypatch.setattr(removals, "remove_edges_at", lambda *_a, **_k: [])
    patch_alias_rows(monkeypatch)
    monkeypatch.setattr(
        semantic_bwb, "law_articles", lambda store, field, law_id: iter([])
    )


def _make_tk_document(key: str, text: str) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["TK", "Strafrecht"],
        "type": NodeType.DOCUMENT.value,
        "props": {"title": text},
    }


def _make_instrument(key: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["Instrument"],
        "type": NodeType.INSTRUMENT.value,
        "props": props,
    }


def _make_article(key: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "_key": key,
        "labels": ["Article"],
        "type": NodeType.ARTICLE.value,
        "props": props,
    }


def _load_config() -> dict[str, Any]:
    return {
        "code_aliases": {"Sr": "BWBR0001854"},
        "instrument_aliases": {"Wetboek van Strafrecht": ("BWBR0001854", None)},
    }


def test_detect_tk_citations_include_article_alias() -> None:
    text = "Wijziging van artikel 287 Sr"
    hits = detect_tk_citations(
        text, _load_config()["code_aliases"], _load_config()["instrument_aliases"]
    )
    assert hits
    article_hits = [hit for hit in hits if hit.kind == "article"]
    assert article_hits
    assert article_hits[0].bwb_id == "BWBR0001854"
    assert article_hits[0].article_number == "287"


def test_tk_pipeline_links_to_article_node() -> None:
    doc = _make_tk_document("tk-1", "Wijziging van artikel 287 Sr")
    article_key = make_node_key("BWBR0001854", "287")
    article = _make_article(
        article_key, {"bwb_id": "BWBR0001854", "article_number": "287"}
    )
    store = _store(
        documents=[doc],
        instruments={
            make_node_key("BWBR0001854"): _make_instrument(
                make_node_key("BWBR0001854"),
                {
                    "bwb_id": "BWBR0001854",
                    "short_title": "Sr",
                    "title": "Wetboek van Strafrecht",
                },
            )
        },
        articles={article_key: article},
    )
    pipeline = TKSemanticPipeline(store=store)

    created = pipeline.run()
    assert created.created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_REFERS_TO
    assert edge["source"] == "tk-article-linker"
    assert isinstance(edge["confidence"], float)


def test_tk_edge_names_the_parts_of_the_article_as_a_judgment_edge_does() -> None:
    doc = _make_tk_document("tk-1", "Wijziging van artikel 287, derde lid, onder a, Sr")
    article_key = make_node_key("BWBR0001854", "287")
    store = _store(
        documents=[doc],
        instruments={
            make_node_key("BWBR0001854"): _make_instrument(
                make_node_key("BWBR0001854"),
                {"bwb_id": "BWBR0001854", "short_title": "Sr"},
            )
        },
        articles={
            article_key: _make_article(
                article_key, {"bwb_id": "BWBR0001854", "article_number": "287"}
            )
        },
    )

    TKSemanticPipeline(store=store).run()

    (edge,) = store.edges.values()
    assert edge["meta"]["qualifier"] == "derde lid, onder a"
    assert edge["meta"]["leden"] == ["3"]
    assert edge["meta"]["onderdelen"] == ["a"]
    assert "aanhef" not in edge["meta"]  # nothing named: empty values are left out


def test_tk_pipeline_links_to_celex_instrument() -> None:
    text = "Implementatie van CELEX:32019L1158"
    doc = _make_tk_document("tk-2", text)
    celex_key = make_node_key("32019L1158")
    instrument = _make_instrument(celex_key, {"celex": "32019L1158"})
    store = _store(
        documents=[doc],
        instruments={celex_key: instrument},
        articles={},
    )
    pipeline = TKSemanticPipeline(store=store)

    created = pipeline.run()
    assert created.created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["_to"].split("/")[0] == "instruments"


def test_tk_pipeline_links_named_act_to_instrument() -> None:
    text = "Deze wijziging betreft het Wetboek van Strafrecht."
    doc = _make_tk_document("tk-3", text)
    instr_key = make_node_key("BWBR0001854")
    instrument = _make_instrument(
        instr_key, {"bwb_id": "BWBR0001854", "title": "Wetboek van Strafrecht"}
    )
    store = _store(
        documents=[doc],
        instruments={instr_key: instrument},
        articles={},
    )
    pipeline = TKSemanticPipeline(store=store)

    created = pipeline.run()
    assert created.created == 1
    assert len(store.edges) == 1


def test_tk_pipeline_idempotent_edges() -> None:
    doc = _make_tk_document("tk-4", "Wijziging van artikel 287 Sr")
    article_key = make_node_key("BWBR0001854", "287")
    article = _make_article(
        article_key, {"bwb_id": "BWBR0001854", "article_number": "287"}
    )
    store = _store(
        documents=[doc],
        instruments={
            make_node_key("BWBR0001854"): _make_instrument(
                make_node_key("BWBR0001854"),
                {
                    "bwb_id": "BWBR0001854",
                    "short_title": "Sr",
                    "title": "Wetboek van Strafrecht",
                },
            )
        },
        articles={article_key: article},
    )
    pipeline = TKSemanticPipeline(store=store)

    first = pipeline.run()
    second = pipeline.run()
    assert first.created == 1
    assert second.created == 0
    assert len(store.edges) == 1


def test_tk_pipeline_reads_the_footnotes_of_a_kamerstuk_too() -> None:
    """``normalize tk-content`` keeps a footnote out of ``text``; a citation in it counts."""
    doc = _make_tk_document("tk-5", "Een memorie zonder verwijzing.")
    doc["props"]["text"] = "Een memorie zonder verwijzing."
    doc["props"]["footnotes"] = [
        {"number": "1", "text": "Zie artikel 287 Sr."},
        {"number": "2", "text": "Kamerstukken II 2019/20, 35 000, nr. 3."},
    ]
    article_key = make_node_key("BWBR0001854", "287")
    store = _store(
        documents=[doc],
        instruments={
            make_node_key("BWBR0001854"): _make_instrument(
                make_node_key("BWBR0001854"),
                {
                    "bwb_id": "BWBR0001854",
                    "short_title": "Sr",
                    "title": "Wetboek van Strafrecht",
                },
            )
        },
        articles={
            article_key: _make_article(
                article_key, {"bwb_id": "BWBR0001854", "article_number": "287"}
            )
        },
    )
    assert TKSemanticPipeline(store=store).run().created == 1
    (edge,) = store.edges.values()
    meta, place = edge["meta"], edge["meta"]["place"]
    assert (place["part"], place["footnote"], place["footnote_id"]) == (
        "footnote",
        "1",
        "fn-1",
    )
    note = doc["props"]["footnotes"][0]["text"]
    assert note[place["start"] : place["end"]] == meta["raw_match"] == "artikel 287 Sr"
    assert meta["snippet"] == note


def test_a_citation_in_the_text_names_its_section() -> None:
    doc = _make_tk_document("tk-6", "Memorie van toelichting")
    text = "ALGEMEEN\nInleiding.\nArtikel I\nDit wijzigt artikel 287 Sr."
    start = text.index("Artikel I")
    doc["props"]["text"] = text
    doc["props"]["sections"] = [
        {"id": "s-1", "char_start": 0, "char_end": start - 1},
        {"id": "s-2", "char_start": start, "char_end": len(text)},
    ]
    article_key = make_node_key("BWBR0001854", "287")
    store = _store(
        documents=[doc],
        instruments={
            make_node_key("BWBR0001854"): _make_instrument(
                make_node_key("BWBR0001854"),
                {"bwb_id": "BWBR0001854", "short_title": "Sr"},
            )
        },
        articles={
            article_key: _make_article(
                article_key, {"bwb_id": "BWBR0001854", "article_number": "287"}
            )
        },
    )
    TKSemanticPipeline(store=store).run()
    (edge,) = store.edges.values()
    place = edge["meta"]["place"]
    assert (place["part"], place["section_id"]) == ("text", "s-2")
    assert text[place["start"] : place["end"]] == edge["meta"]["raw_match"]


def test_an_abbreviation_names_its_law_as_written() -> None:
    codes = {"EVRM": "BWBV0001000", "AVG": "32016R0679"}

    hits = detect_tk_citations("Dit past binnen het EVRM en de AVG.", codes, {})

    named = {(h.kind, h.bwb_id, h.celex) for h in hits}
    assert ("instrument", "BWBV0001000", None) in named
    assert ("instrument", None, "32016R0679") in named
    assert not detect_tk_citations("evrm en avg in kleine letters", codes, {})
    # the law of an article citation: the article is cited, not the law besides
    cited = detect_tk_citations("Zie artikel 8, eerste lid, van het EVRM.", codes, {})
    assert [h.kind for h in cited] == ["article"]


def test_the_record_a_paper_came_with_is_no_text_of_it() -> None:
    """The record's ``Titel`` is the dossier's title, its actors name factions: neither is
    read, only the paper's title, text and footnotes."""
    doc = _make_tk_document("tk-6", "Motie van het lid Kathmann over een meldloket")
    doc["props"]["raw"] = {
        "Titel": "Wijziging van het Wetboek van Strafrecht",
        "DocumentActor": [{"ActorNaam": "Bikkers", "ActorFractie": "Sr"}],
    }
    store = _store(
        documents=[doc],
        instruments={
            make_node_key("BWBR0001854"): _make_instrument(
                make_node_key("BWBR0001854"),
                {
                    "bwb_id": "BWBR0001854",
                    "short_title": "Sr",
                    "title": "Wetboek van Strafrecht",
                },
            )
        },
        articles={},
    )

    assert TKSemanticPipeline(store=store).run().created == 0
