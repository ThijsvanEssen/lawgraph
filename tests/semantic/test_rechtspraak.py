from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.models import NodeType, make_node_key
from lawgraph.db.queries import instrument_names, removals
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.pipelines.semantic.rechtspraak import (
    RechtspraakSemanticPipeline,
)
from tests.fakes import InMemoryStore


class _Store(InMemoryStore):
    """The judgments and articles of the graph, and the alias rows of the instruments."""

    def __init__(
        self,
        judgments: list[dict[str, Any]],
        articles: dict[str, dict[str, Any]],
        instruments: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__({"judgments": judgments, "articles": articles.values()})
        self.alias_rows = instruments or []


@pytest.fixture(autouse=True)
def _queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """The judgments normalize made and the names of the instruments come from the fake
    store; no law has its articles loaded, and nothing is removed."""
    monkeypatch.setattr(
        instrument_names,
        "code_alias_rows",
        lambda store: iter(list(store.alias_rows)),
    )
    for name in ("instrument_alias_rows", "law_date_rows"):
        monkeypatch.setattr(
            semantic_bwb, name, lambda store: iter(list(store.alias_rows))
        )
    monkeypatch.setattr(
        semantic_rechtspraak,
        "count_rechtspraak_judgments",
        lambda store: len(store.nodes["judgments"]),
    )
    monkeypatch.setattr(
        semantic_rechtspraak,
        "judgment_paragraphs",
        lambda store, *, eclis, batch_size, after=None, limit=None: iter(
            list(store.nodes["judgments"].values())
        ),
    )
    monkeypatch.setattr(
        semantic_bwb, "law_articles", lambda store, field, law_id: iter([])
    )
    monkeypatch.setattr(removals, "remove_edges_at", lambda *_a, **_k: [])


def _paragraph(number: str | None, text: str) -> dict[str, Any]:
    slug = f"rov-{number}" if number else "p-1"
    return {"id": slug, "number": number, "kind": "body", "text": text}


def _judgment_doc(paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": "ecli_nl_hr_2019_793",
        "labels": ["Rechtspraak"],
        "type": NodeType.JUDGMENT.value,
        "props": {"ecli": "ECLI:NL:HR:2019:793", "paragraphs": paragraphs},
    }


def _make_article_doc() -> dict[str, Any]:
    return {
        "key": make_node_key("BWBR0001854", "287"),
        "labels": ["BWB", "Article"],
        "type": NodeType.ARTICLE.value,
        "props": {
            "bwb_id": "BWBR0001854",
            "article_number": "287",
        },
    }


_SR = {"short_title": "Sr", "bwb_id": "BWBR0001854", "celex": None}


def _run(
    paragraphs: list[dict[str, Any]],
    instruments: list[dict[str, Any]] | None = None,
    articles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    article = _make_article_doc()
    store = _Store(
        judgments=[_judgment_doc(paragraphs)],
        articles=articles if articles is not None else {article["key"]: article},
        instruments=instruments if instruments is not None else [_SR],
    )
    RechtspraakSemanticPipeline(store=store).run()
    return store.edges


def test_rechtspraak_article_semantic_pipeline_idempotent_edges() -> None:
    article_doc = _make_article_doc()
    store = _Store(
        judgments=[
            _judgment_doc([_paragraph("2.1", "Dit is een tekst met art. 287 Sr.")])
        ],
        articles={article_doc["key"]: article_doc},
        instruments=[_SR],
    )
    pipeline = RechtspraakSemanticPipeline(store=store)

    created_first = pipeline.run()
    assert created_first.created == 1
    assert len(store.edges) == 1

    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_REFERS_TO
    assert edge["source"] == "rechtspraak-article-linker"
    assert isinstance(edge["confidence"], float)

    created_second = pipeline.run()
    assert created_second.created == 0
    assert len(store.edges) == 1


def test_a_citation_repeated_in_a_paragraph_is_a_mention_at_each_place() -> None:
    text = "Volgens art. 287 Sr is het zo; anders dan art. 287, derde lid, Sr."
    edges = _run([_paragraph("5.3", text)])

    (edge,) = edges.values()
    first, second = edge["meta"]["mentions"]
    assert edge["meta"]["mention_count"] == 2
    assert text[first["start"] : first["end"]] == first["raw_match"] == "art. 287 Sr"
    assert text[second["start"] : second["end"]] == "art. 287, derde lid, Sr"
    assert first["start"] < first["end"] <= second["start"]
    assert (first["leden"], second["leden"]) == ([], ["3"])
    assert second["qualifier"] == "derde lid"
    assert {m["paragraph_id"] for m in (first, second)} == {"rov-5.3"}
    assert first["paragraph_number"] == "5.3"


def test_the_mentions_of_an_article_are_kept_per_paragraph() -> None:
    edges = _run(
        [
            _paragraph("2.1", "Art. 287 Sr is van toepassing."),
            _paragraph(None, "Zonder cijfer."),
            _paragraph("2.2", "Dat volgt uit art. 287, eerste lid, onder a, Sr."),
        ]
    )

    (edge,) = edges.values()
    assert [
        (m["paragraph_id"], m.get("paragraph_number")) for m in edge["meta"]["mentions"]
    ] == [
        ("rov-2.1", "2.1"),
        ("rov-2.2", "2.2"),
    ]
    last = edge["meta"]["mentions"][1]
    assert (last["leden"], last["onderdelen"], last["aanhef"]) == (["1"], ["a"], False)
    assert last["snippet"] and last["confidence"] == edge["confidence"] == 0.95


def test_a_law_named_in_the_paragraph_before_is_still_the_law_meant() -> None:
    """The judgment is read as one text: "die wet" reaches over the paragraph break."""
    instruments = [
        {"bwb_id": "BWBR0005537", "celex": None, "title": "Algemene wet bestuursrecht"}
    ]
    articles = {
        make_node_key("BWBR0005537", key): {
            "key": make_node_key("BWBR0005537", key),
            "type": NodeType.ARTICLE.value,
            "props": {"bwb_id": "BWBR0005537", "article_number": key},
        }
        for key in ("8:29", "8:30")
    }
    edges = _run(
        [
            _paragraph(
                "1.1", "Volgens artikel 8:29 van de Algemene wet bestuursrecht moet"
            ),
            _paragraph("1.2", "Ook artikel 8:30 van die wet is van belang."),
        ],
        instruments=instruments,
        articles=articles,
    )

    by_target = {e["to_id"]: e for e in edges.values()}
    second = by_target["articles/bwbr0005537_8_30"]["meta"]["mentions"][0]
    assert second["paragraph_id"] == "rov-1.2"
    assert second["raw_match"] == "artikel 8:30 van die wet"
    assert second["confidence"] == 0.7


def test_a_judgment_without_paragraphs_links_nothing() -> None:
    store = _Store(
        judgments=[_judgment_doc([])],
        articles={_make_article_doc()["key"]: _make_article_doc()},
        instruments=[_SR],
    )
    RechtspraakSemanticPipeline(store=store).run()
    assert store.edges == {}


def test_a_title_two_laws_share_is_no_alias() -> None:
    instruments = [
        {
            "bwb_id": "BWBR0005537",
            "celex": None,
            "title": "Wet gelijk",
            "citation_title": None,
        },
        {
            "bwb_id": "BWBR0001854",
            "celex": None,
            "title": "Wet gelijk",
            "citation_title": None,
        },
    ]
    assert _run([_paragraph("1", "artikel 8:29 van de Wet gelijk")], instruments) == {}


class _Judgments:
    """Three judgments as ``normalize rechtspraak`` made them; the calls record the filters."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.eclis: list[list[str] | None] = []  # the filter of each paragraphs query
        self.recent: list[str] = []  # the since of each query for the recent ECLIs
        self.pulled = 0
        monkeypatch.setattr(
            semantic_rechtspraak, "judgment_paragraphs", self.judgment_paragraphs
        )
        monkeypatch.setattr(
            semantic_rechtspraak, "count_rechtspraak_judgments", lambda store: 3
        )
        monkeypatch.setattr(
            raw_queries, "judgment_eclis_fetched_since", self.eclis_fetched_since
        )
        # the citations the text no longer makes
        monkeypatch.setattr(removals, "remove_edges_at", lambda *a, **kw: [])

    def eclis_fetched_since(self, store, since_iso):
        self.recent.append(since_iso)
        return iter(["ECLI:NL:HR:2020:1"])

    def judgment_paragraphs(self, store, *, eclis, batch_size, after=None, limit=None):
        self.eclis.append(eclis)
        for n in range(3):
            self.pulled += 1
            yield {
                "key": f"ecli_nl_hr_2020_{n}",
                "type": "judgment",
                "labels": ["Rechtspraak"],
                "props": {
                    "ecli": f"ECLI:NL:HR:2020:{n}",
                    "paragraphs": [
                        {"id": "p-1", "number": None, "kind": "body", "text": "x"}
                    ],
                },
            }


def _linker(store):
    pipeline = RechtspraakSemanticPipeline(store=store)
    pipeline._load_code_choices = lambda: ({"Sr": "BWBR0001854"}, {})
    pipeline._load_instrument_aliases = dict
    pipeline._load_law_dates = dict
    return pipeline


def test_the_article_linker_reads_the_paragraphs_normalize_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not the XML: the paragraphs it serves are the ones whose ids it records."""
    judgments = _Judgments(monkeypatch)
    result = _linker(InMemoryStore()).run()
    assert result.errors == [] and judgments.pulled == 3
    assert judgments.eclis == [None] and judgments.recent == []


def test_an_incremental_run_asks_for_the_judgments_retrieved_since(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judgments = _Judgments(monkeypatch)
    _linker(InMemoryStore()).run(since=dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    assert judgments.recent == ["2025-01-01T00:00:00Z"]
    assert judgments.eclis == [["ECLI:NL:HR:2020:1"]]
