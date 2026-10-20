"""``normalize tk-content``: the text and the sections of stored Kamerstuk XML, on Documents."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core import document_xml
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.props import DocumentProps
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.normalize.tk_content import TKContentNormalizePipeline
from tests.fakes import InMemoryStore, count_calls
from tests.paths import fixture_text


def _store(*documents: str) -> InMemoryStore:
    """A store with the Documents that exist, each without props yet."""
    return InMemoryStore(
        {"documents": [{"key": key, "props": {}} for key in documents]}
    )


def _written(store: InMemoryStore) -> list[Node]:
    """The Documents the pipeline wrote props on."""
    return [
        Node.from_document("documents", doc)
        for doc in store.nodes["documents"].values()
        if doc["props"]
    ]


def _raw(identifier: str, name: str | None, document: str | None) -> dict[str, Any]:
    xml = fixture_text(f"{name}.xml") if name else None
    return {
        "external_id": identifier,
        "payload_text": xml,
        "meta": {"document": document} if document else {},
    }


def _run(store: InMemoryStore, *records: dict[str, Any]) -> tuple[PipelineResult, int]:
    pipeline = TKContentNormalizePipeline(store=store)
    result = PipelineResult()
    pipeline.write(iter(records), result)
    pipeline.add_outcomes(result)
    writes = pipeline.store.writes
    return result, writes.nodes_created + writes.nodes_updated + writes.nodes_unchanged


def test_the_text_and_the_sections_are_written_on_the_existing_document() -> None:
    store = _store("doc-1")
    result, count = _run(store, _raw("kst-36750-3", "kst_36750_3", "doc-1"))
    assert count == 1 and result.skipped == 0
    (node,) = _written(store)
    assert (node.collection, node.key, node.type) == (
        "documents",
        "doc-1",
        NodeType.DOCUMENT,
    )
    props = node.props
    assert props["text"].startswith("MEMORIE VAN TOELICHTING\n")
    assert props["text_source"] == "kst-xml" and props["text_truncated"] is False
    assert props["xml_dialect"] == "officiele-publicatie"
    assert props["structure_quality"] == "explicit" and props["budget"] is False
    kinds = [s["kind"] for s in props["sections"]]
    assert kinds.count("article") == 2 and "artikelsgewijs" in kinds
    assert len(props["footnotes"]) == 19
    assert all(0 < n["at"] <= len(props["text"]) for n in props["footnotes"])
    # offsets are into the text that is stored next to them
    article = next(s for s in props["sections"] if s["kind"] == "article")
    assert props["text"][article["char_start"] : article["char_end"]].startswith(
        article["heading"]
    )
    DocumentProps.model_validate(props)  # every field is one of the schema


def test_only_the_props_of_the_text_are_written() -> None:
    """A shallow merge: what ``normalize tk-dossiers`` wrote stays."""
    store = _store("doc-1")
    _run(store, _raw("kst-36750-3", "kst_36750_3", "doc-1"))
    assert set(_written(store)[0].props) == {
        "text",
        "text_source",
        "text_truncated",
        "xml_dialect",
        "structure_quality",
        "budget",
        "sections",
        "footnotes",
        "tables",
        "dictum",
        "explanation",
    }


def test_a_paper_without_a_document_is_left_for_a_run_after_normalize_tk_dossiers() -> (
    None
):
    store = _store("doc-2")
    result, count = _run(
        store,
        _raw("kst-36750-3", "kst_36750_3", "doc-1"),
        _raw("kst-25823-3", "kst_25823_3", "doc-2"),
    )
    assert count == 1 and result.skipped == 1
    assert [n.key for n in _written(store)] == ["doc-2"]


def test_a_record_that_cannot_be_read_is_skipped_and_the_rest_goes_on() -> None:
    store = _store("doc-1", "doc-2", "doc-3", "doc-4")
    broken = {
        "external_id": "kst-1-1",
        "payload_text": "<html>Bad gateway",
        "meta": {"document": "doc-1"},
    }
    result, count = _run(
        store,
        broken,
        _raw("kst-1-2", None, "doc-2"),  # no payload
        _raw("kst-1-3", "kst_25823_3", None),  # no document
        _raw("kst-25823-3", "kst_25823_3", "doc-4"),
    )
    assert count == 1 and result.skipped == 3
    assert [n.key for n in _written(store)] == ["doc-4"]


def test_documents_are_looked_up_a_batch_at_a_time_not_one_by_one() -> None:
    store = _store(*(f"doc-{n}" for n in range(45)))
    lookups = count_calls(store, "existing_keys")
    records = [_raw(f"kst-{n}-1", "kst_28844_269", f"doc-{n}") for n in range(45)]
    _, count = _run(store, *records)
    assert count == 45 and lookups["existing_keys"] == 3  # 20 + 20 + 5


def test_reading_asks_for_the_xml_records_of_tk_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[dict[str, Any]] = []

    def iter_raw_records(store: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        asked.append(kwargs)
        return iter([])

    monkeypatch.setattr(raw_queries, "count_raw_records", lambda *_: 0)
    monkeypatch.setattr(raw_queries, "iter_raw_records", iter_raw_records)
    pipeline = TKContentNormalizePipeline(store=InMemoryStore())
    list(pipeline.fetch_raw())
    assert [(a["source"], a["kinds"]) for a in asked] == [
        (SOURCE_TK, [RAW_KIND_TK_KAMERSTUK_XML])
    ]


def test_xml_that_does_not_read_is_a_note_of_the_step_with_its_first_record() -> None:
    """Kapotte XML is not an empty paper: the step names it, its count and the first one."""
    store = _store("doc-1", "doc-2", "doc-3")
    broken = {
        "payload_text": "<kamerwrk><body>Afgebroken",
        "meta": {"document": "doc-1"},
    }
    html = {
        "payload_text": "<html><body>Bad gateway</body></html>",
        "meta": {"document": "doc-2"},
    }
    result, count = _run(
        store,
        {**broken, "external_id": "kst-1-1"},
        {**html, "external_id": "kst-1-2"},
        _raw("kst-25823-3", "kst_25823_3", "doc-3"),
    )
    assert count == 1 and result.skipped == 2 and result.errors == []
    (note,) = result.notes
    assert note.startswith(
        "2 x Kamerstuk XML that does not read (first: kst-1-1: not XML: "
    )


def test_a_paper_without_sections_is_a_note_of_the_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*_args: Any) -> list[Any]:
        raise RuntimeError("a paper nobody expected")

    monkeypatch.setattr(document_xml, "_sections", broken)
    store = _store("doc-1")
    result, count = _run(store, _raw("kst-36750-3", "kst_36750_3", "doc-1"))
    assert count == 1 and result.errors == []
    assert result.notes == [
        "1 x Kamerstuk XML without sections (its text only) "
        "(first: kst-36750-3: RuntimeError: a paper nobody expected)"
    ]
