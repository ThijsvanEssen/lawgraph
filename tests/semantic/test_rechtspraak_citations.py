"""Tests for the rechtspraak-citations semantic pipeline."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import RELATION_REFERS_TO
from lawgraph.core.identifiers import find_eclis
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.pipelines.semantic.rechtspraak_citations import (
    RechtspraakCitationsSemanticPipeline,
)
from tests.fakes import InMemoryStore

# ---------------------------------------------------------------------------
# Pure detection helper
# ---------------------------------------------------------------------------


def test_detect_ecli_references_finds_single() -> None:
    hits = find_eclis("Zie ECLI:NL:HR:2020:1234 voor context.")
    assert hits == ["ECLI:NL:HR:2020:1234"]


def test_detect_ecli_references_deduplicates() -> None:
    text = "ECLI:NL:HR:2020:1234 en nogmaals ECLI:NL:HR:2020:1234"
    hits = find_eclis(text)
    assert hits == ["ECLI:NL:HR:2020:1234"]


def test_detect_ecli_references_multiple() -> None:
    text = "ECLI:NL:HR:2020:1234 en ECLI:NL:RBAMS:2021:5678"
    hits = find_eclis(text)
    assert len(hits) == 2


def test_detect_ecli_references_empty() -> None:
    assert find_eclis("") == []
    assert find_eclis(None) == []


# ---------------------------------------------------------------------------
# Pipeline smoke test
# ---------------------------------------------------------------------------


class _Store(InMemoryStore):
    """The judgments of the graph, and the stored judgments with their XML as
    ``with_payloads`` passes them on."""

    def __init__(
        self,
        *,
        judgment_docs: list[dict[str, Any]],
        judgments: list[Node] | None = None,
    ) -> None:
        super().__init__(
            {"judgments": [node.to_document() for node in judgments or []]}
        )
        self.payload_rows = [
            {"ecli": d["props"]["ecli"], "payload_text": d["props"]["raw_xml"]}
            for d in judgment_docs
        ]


@pytest.fixture()
def reads(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """The judgments come from the fake store; the ECLI lookup and the procedural edges
    find nothing, and nothing is removed. The *since_iso* of every read of the judgments."""
    since: list[str | None] = []

    def judgment_payload_refs(
        store: _Store, *, since_iso: str | None, batch_size: int
    ) -> Iterator[dict[str, Any]]:
        since.append(since_iso)
        return iter(store.payload_rows)

    monkeypatch.setattr(raw_queries, "count_judgment_records", lambda store: None)
    monkeypatch.setattr(raw_queries, "judgment_payload_refs", judgment_payload_refs)
    monkeypatch.setattr(
        semantic_rechtspraak, "judgment_ids_by_ecli", lambda store, eclis: iter([])
    )
    monkeypatch.setattr(
        semantic_rechtspraak,
        "procedural_neighbours",
        lambda store, ids, relations: iter([]),
    )
    monkeypatch.setattr(semantic_edges, "remove_edges_from", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        semantic_rechtspraak, "remove_unreached_judgment_stubs", lambda store: 0
    )
    return since


def _make_judgment(key: str, ecli: str, text: str, related: str = "") -> dict[str, Any]:
    """A judgment whose XML holds *text* in its uitspraak and *related* in its metadata."""
    xml = (
        '<open-rechtspraak xmlns:dcterms="http://purl.org/dc/terms/"><rdf>'
        f"<dcterms:relation>{related}</dcterms:relation></rdf>"
        f"<uitspraak><para>{text}</para></uitspraak></open-rechtspraak>"
    )
    return {
        "_key": key,
        "_id": f"judgments/{key}",
        "type": NodeType.JUDGMENT.value,
        "labels": [],
        "props": {"ecli": ecli, "raw_xml": xml},
    }


def test_pipeline_creates_cites_judgment_edge(reads: list[str | None]) -> None:
    source_ecli = "ECLI:NL:HR:2020:1234"
    target_ecli = "ECLI:NL:HR:2019:9876"
    source_doc = _make_judgment(
        make_node_key(source_ecli),
        source_ecli,
        f"Zie het arrest {target_ecli} voor de onderbouwing.",
        # the metadata names the conclusion: procedure, not a citation
        related="ECLI:NL:PHR:2020:1",
    )
    target_key = make_node_key(target_ecli)
    target_node = Node(
        collection="judgments",
        type=NodeType.JUDGMENT,
        key=target_key,
        props={"ecli": target_ecli},
        _skip_validation=True,
    )
    store = _Store(judgment_docs=[source_doc], judgments=[target_node])
    pipeline = RechtspraakCitationsSemanticPipeline(store=store)
    result = pipeline.run()

    assert result.created == 1
    assert len(store.edges) == 1
    edge = next(iter(store.edges.values()))
    assert edge["relation"] == RELATION_REFERS_TO
    assert edge["_from"].startswith("judgments/")
    assert edge["_to"].startswith("judgments/")


def test_pipeline_skips_self_reference(reads: list[str | None]) -> None:
    ecli = "ECLI:NL:HR:2020:1234"
    doc = _make_judgment(
        make_node_key(ecli), ecli, f"Dit arrest ({ecli}) overweegt dat..."
    )
    store = _Store(judgment_docs=[doc])
    pipeline = RechtspraakCitationsSemanticPipeline(store=store)
    result = pipeline.run()
    assert result.created == 0


def test_an_incremental_run_reads_the_judgments_fetched_since(
    reads: list[str | None],
) -> None:
    """The judgments read before have their edges; a cited judgment has the key of its stub."""
    import datetime as dt

    pipeline = RechtspraakCitationsSemanticPipeline(store=_Store(judgment_docs=[]))
    pipeline.run(since=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc))
    assert reads == ["2025-01-01T00:00:00Z"]


def test_the_places_that_name_a_cited_judgment() -> None:
    from lawgraph.core.mentions import Mention
    from lawgraph.pipelines.semantic.rechtspraak_citations import judgment_mentions

    by_ecli, by_appno = judgment_mentions(
        [
            {"id": "rov-1.1", "number": "1.1", "text": "Zie ECLI:NL:HR:2015:1."},
            {
                "id": "p-ab12cd34",
                "number": None,
                "text": "Ook LJN BK9271, zonder nummer.",
            },
            {
                "id": "rov-1.1",
                "number": "1.1",
                "text": "HR 1 mei 2015, ECLI:NL:HR:2015:1; EHRM 28 maart 2000, nr. 22492/93.",
                "footnote": "3",
            },
        ],
        {"BK9271": "ECLI:NL:CRVB:2010:BK9271"},
    )
    first, in_note = by_ecli["ECLI:NL:HR:2015:1"]
    assert (first.paragraph_id, first.paragraph_number, first.footnote) == (
        "rov-1.1",
        "1.1",
        None,
    )
    assert (first.start, first.end, first.raw_match) == (4, 21, "ECLI:NL:HR:2015:1")
    assert (in_note.footnote, in_note.raw_match) == ("3", "ECLI:NL:HR:2015:1")
    (ljn,) = by_ecli["ECLI:NL:CRVB:2010:BK9271"]
    assert (ljn.paragraph_id, ljn.raw_match) == ("p-ab12cd34", "LJN BK9271")
    (echr,) = by_appno["22492/93"]
    assert echr.raw_match == "EHRM 28 maart 2000, nr. 22492/93"
    stored = first.to_dict(parts=False)
    assert "leden" not in stored and Mention.from_dict(stored) == first


def test_a_citation_in_a_footnote_says_where_it_stands(reads: list[str | None]) -> None:
    """Urgenda cites its judgments in footnotes: the edge names the footnote, the paragraph
    that refers to it and the offsets in the footnote's text."""
    source_ecli, target_ecli = "ECLI:NL:HR:2019:2006", "ECLI:NL:HR:1988:AD5713"
    note = f"Zie HR 23 september 1988, {target_ecli} (Kalimijnen)."
    xml = (
        "<open-rechtspraak><uitspraak><section><paragroup><nr>5.7.6.</nr>"
        "<para>De Staat is aansprakelijk.<footnote-ref linkend='f35'/></para>"
        f"</paragroup></section><footnote id='f35' label='35'><para>{note}</para>"
        "</footnote></uitspraak></open-rechtspraak>"
    )
    doc = _make_judgment(make_node_key(source_ecli), source_ecli, "")
    doc["props"]["raw_xml"] = xml
    store = _Store(judgment_docs=[doc])
    RechtspraakCitationsSemanticPipeline(store=store).run()

    (edge,) = store.edges.values()
    meta = edge["meta"]
    assert meta["cited_ecli"] == target_ecli
    assert meta["paragraphs"] == ["5.7.6"]
    assert meta["mention_count"] == 1
    (mention,) = meta["mentions"]
    assert mention["paragraph_id"] == "rov-5.7.6"
    assert mention["footnote"] == "35"
    assert note[mention["start"] : mention["end"]] == target_ecli
    assert mention["snippet"] == note


def test_an_unreadable_judgment_fails_the_step_and_names_its_ecli(
    reads: list[str | None], caplog: pytest.LogCaptureFixture
) -> None:
    """The rest is read; the run ends with one error for the cause, with the ECLI."""
    good, broken = "ECLI:NL:HR:2020:1", "ECLI:NL:HR:2020:2"
    docs = [
        _make_judgment(make_node_key(good), good, "Zie ECLI:NL:HR:2019:9."),
        {
            **_make_judgment(make_node_key(broken), broken, ""),
            "props": {"ecli": broken, "raw_xml": "<open-rechtspraak><uitspraak>"},
        },
    ]
    with caplog.at_level(logging.WARNING):
        result = RechtspraakCitationsSemanticPipeline(
            store=_FakeStore(judgment_docs=docs)
        ).run()

    assert result.skipped == 1
    (error,) = result.errors
    assert "unreadable judgment XML" in error and broken in error
    assert any(broken in message for message in caplog.messages)


def test_a_judgment_without_stored_xml_is_counted_as_skipped(
    reads: list[str | None],
) -> None:
    ecli = "ECLI:NL:HR:2020:1"
    store = _FakeStore(judgment_docs=[_make_judgment(make_node_key(ecli), ecli, "")])
    store.payload_rows = lambda: [{"ecli": ecli, "payload_text": None}]  # type: ignore[method-assign]

    result = RechtspraakCitationsSemanticPipeline(store=store).run()

    assert (result.skipped, result.errors) == (1, [])
