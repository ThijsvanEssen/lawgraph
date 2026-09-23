"""``normalize tk-content``: the text and the sections of stored Kamerstuk XML, on Documents."""

from __future__ import annotations

import pathlib
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.props import DocumentProps
from lawgraph.pipelines.normalize.tk_content import TKContentNormalizePipeline
from tests.fakes import RawSourcesFake

FIXTURES = pathlib.Path(__file__).parents[1] / "fixtures"


class _Store(RawSourcesFake):
    """The nodes that exist, and what is written to them."""

    def __init__(self, documents: set[str]) -> None:
        self.documents = documents
        self.upserted: list[Node] = []
        self.lookups: list[list[str]] = []
        self.queries: list[tuple[str, dict]] = []

    def query(self, aql: str, bind_vars: dict | None = None, **_kw: Any) -> list[Any]:
        self.queries.append((aql, dict(bind_vars or {})))
        return []

    def existing_keys(self, collection: str, keys: Any) -> set[str]:
        self.lookups.append(sorted(keys))
        return {key for key in keys if key in self.documents}

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        self.upserted.extend(Node.from_document(collection, d) for d in docs)
        return 0, len(docs)


def _raw(identifier: str, name: str | None, document: str | None) -> dict[str, Any]:
    xml = (FIXTURES / f"{name}.xml").read_text(encoding="utf-8") if name else None
    return {
        "external_id": identifier,
        "payload_text": xml,
        "meta": {"document": document} if document else {},
    }


def _run(store: _Store, *records: dict[str, Any]) -> tuple[PipelineResult, int]:
    pipeline = TKContentNormalizePipeline(store=store)  # type: ignore[arg-type]
    result = PipelineResult()
    return result, pipeline.normalize_nodes(iter(records), result)


def test_the_text_and_the_sections_are_written_on_the_existing_document() -> None:
    store = _Store({"doc-1"})
    result, count = _run(store, _raw("kst-36750-3", "kst_36750_3", "doc-1"))
    assert count == 1 and result.skipped == 0
    (node,) = store.upserted
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
    # offsets are into the text that is stored next to them
    article = next(s for s in props["sections"] if s["kind"] == "article")
    assert props["text"][article["char_start"] : article["char_end"]].startswith(
        article["heading"]
    )
    DocumentProps.model_validate(props)  # every field is one of the schema


def test_only_the_props_of_the_text_are_written() -> None:
    """A shallow merge: what ``normalize tk-dossiers`` wrote stays."""
    store = _Store({"doc-1"})
    _run(store, _raw("kst-36750-3", "kst_36750_3", "doc-1"))
    assert set(store.upserted[0].props) == {
        "text",
        "text_source",
        "text_truncated",
        "xml_dialect",
        "structure_quality",
        "budget",
        "sections",
        "footnotes",
    }


def test_a_paper_without_a_document_is_left_for_a_run_after_normalize_tk_dossiers() -> (
    None
):
    store = _Store({"doc-2"})
    result, count = _run(
        store,
        _raw("kst-36750-3", "kst_36750_3", "doc-1"),
        _raw("kst-25823-3", "kst_25823_3", "doc-2"),
    )
    assert count == 1 and result.skipped == 1
    assert [n.key for n in store.upserted] == ["doc-2"]


def test_a_record_that_cannot_be_read_is_skipped_and_the_rest_goes_on() -> None:
    store = _Store({"doc-1", "doc-2", "doc-3", "doc-4"})
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
    assert [n.key for n in store.upserted] == ["doc-4"]


def test_documents_are_looked_up_a_batch_at_a_time_not_one_by_one() -> None:
    store = _Store({f"doc-{n}" for n in range(45)})
    records = [_raw(f"kst-{n}-1", "kst_28844_269", f"doc-{n}") for n in range(45)]
    _, count = _run(store, *records)
    assert count == 45 and len(store.lookups) == 3  # 20 + 20 + 5


def test_reading_asks_for_the_xml_records_of_tk_only() -> None:
    store = _Store(set())
    pipeline = TKContentNormalizePipeline(store=store)  # type: ignore[arg-type]
    list(pipeline.fetch_raw())
    assert any(
        bind.get("source") == SOURCE_TK
        and bind.get("kinds") == [RAW_KIND_TK_KAMERSTUK_XML]
        for _, bind in store.queries
    )
