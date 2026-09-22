from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.pipelines.semantic.rechtspraak import (
    RechtspraakSemanticPipeline,
)
from tests.conftest import _BaseFakeStore


class _FakeStore(_BaseFakeStore):
    def __init__(
        self,
        judgments: list[dict[str, Any]],
        articles: dict[str, dict[str, Any]],
        instruments: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._judgments = judgments
        self._articles = articles
        self._instruments = instruments or []

    def query(
        self, aql: str, bind_vars: dict | None = None, **_kw: Any
    ) -> list[dict[str, Any]]:
        if "FOR j IN judgments" in aql:  # the judgments normalize made
            if "COLLECT WITH COUNT" in aql:
                return [len(self._judgments)]
            return list(self._judgments)
        if "FOR inst IN instruments" in aql:
            return list(self._instruments)
        return []

    def get_node(self, collection: str, key: str) -> Node | None:
        doc = self._articles.get(key)
        if doc is None:
            return None
        return Node.from_document(collection, doc)

    def insert_or_update_edge(
        self,
        doc: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        key = doc["_key"]
        created = key not in self.edges
        self.edges[key] = dict(doc)
        return self.edges[key], created


def _paragraph(number: str | None, text: str) -> dict[str, Any]:
    slug = f"rov-{number}" if number else "p-1"
    return {"id": slug, "number": number, "kind": "body", "text": text}


def _judgment_doc(paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "_key": "ecli_nl_hr_2019_793",
        "labels": ["Rechtspraak"],
        "type": NodeType.JUDGMENT.value,
        "props": {"ecli": "ECLI:NL:HR:2019:793", "paragraphs": paragraphs},
    }


def _make_article_doc() -> dict[str, Any]:
    return {
        "_key": make_node_key("BWBR0001854", "287"),
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
    store = _FakeStore(
        judgments=[_judgment_doc(paragraphs)],
        articles=articles if articles is not None else {article["_key"]: article},
        instruments=instruments if instruments is not None else [_SR],
    )
    RechtspraakSemanticPipeline(store=store).run()
    return store.edges


def test_rechtspraak_article_semantic_pipeline_idempotent_edges() -> None:
    article_doc = _make_article_doc()
    store = _FakeStore(
        judgments=[
            _judgment_doc([_paragraph("2.1", "Dit is een tekst met art. 287 Sr.")])
        ],
        articles={article_doc["_key"]: article_doc},
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
            "_key": make_node_key("BWBR0005537", key),
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

    by_target = {e["_to"]: e for e in edges.values()}
    second = by_target["articles/bwbr0005537_8_30"]["meta"]["mentions"][0]
    assert second["paragraph_id"] == "rov-1.2"
    assert second["raw_match"] == "artikel 8:30 van die wet"
    assert second["confidence"] == 0.7


def test_a_judgment_without_paragraphs_links_nothing() -> None:
    store = _FakeStore(
        judgments=[_judgment_doc([])],
        articles={_make_article_doc()["_key"]: _make_article_doc()},
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
