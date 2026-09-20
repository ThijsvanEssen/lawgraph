from __future__ import annotations

import datetime as dt
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_RS_INDEX,
    RAW_SOURCE_KINDS,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.judgments import (
    compose_display_name,
    derive_court_tier,
    extract_judgment_text,
    extract_rdf_metadata,
    extract_sections,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class RechtspraakNormalizePipeline(NormalizePipelineBase):
    """Normalization pipeline that turns Rechtspraak raw dumps into judgment nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read Rechtspraak index and content raw_sources records."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_RECHTSPRAAK])
        rows = self._query_raw_sources(
            source=SOURCE_RECHTSPRAAK, kinds=kinds, since=since
        )
        grouped = self._group_by_kind(rows, kinds=kinds)

        index_records = grouped.get(RAW_KIND_RS_INDEX, [])
        content_records = grouped.get(RAW_KIND_RS_CONTENT, [])

        logger.info(
            "Loaded %d Rechtspraak index records and %d content records from raw_sources.",
            len(index_records),
            len(content_records),
        )

        return {"index": index_records, "content": content_records}

    def _build_content_node(
        self, raw_entry: dict[str, Any]
    ) -> tuple[str | None, Node | None]:
        """Process one content raw_sources entry; return (ecli, Node) or (None, None)."""
        payload_text = self._payload_text(raw_entry)
        meta = self._meta(raw_entry)
        ecli = meta.get("ecli")
        if not ecli:
            logger.warning(
                "Skipping Rechtspraak content record without ECLI (_key=%s).",
                raw_entry.get("_key"),
            )
            return None, None

        props: dict[str, Any] = {
            "source": SOURCE_RECHTSPRAAK,
            "ecli": ecli,
            "raw_xml": payload_text,
        }
        if raw_entry.get("kind"):
            props["source_kind"] = raw_entry["kind"]
        if meta:
            props["meta"] = meta

        summary, text = extract_judgment_text(payload_text)
        if summary:
            props["summary"] = summary
        if text:
            props["text"] = text

        judgment_meta, subjects = extract_rdf_metadata(payload_text)
        if judgment_meta:
            props["judgment_metadata"] = judgment_meta
            for field in ("court", "date", "case_number"):
                if field in judgment_meta:
                    props[field] = judgment_meta[field]
            if judgment_meta.get("related_eclis"):
                props["related_eclis"] = judgment_meta["related_eclis"]
        if subjects:
            props["subjects"] = subjects

        sections = extract_sections(payload_text)
        if sections:
            props["paragraphs"] = sections

        court_code, tier = derive_court_tier(ecli)
        props["court_code"] = court_code
        props["tier"] = tier
        jm_date = judgment_meta.get("date") if isinstance(judgment_meta, dict) else None
        props["date_eff"] = (
            jm_date or (meta.get("date") if meta else None) or props.get("date")
        )
        props["display_name"] = compose_display_name(props)
        node = Node(
            collection=COLLECTION_JUDGMENTS,
            type=NodeType.JUDGMENT,
            key=make_node_key(ecli),
            labels=["Rechtspraak"],
            props=props,
        )
        return ecli, node

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Convert Rechtspraak content payloads into judgment nodes."""
        judgments_by_ecli: dict[str, Node] = {}
        with NodeWriter(self.store) as writer:
            for raw_entry in raw.get("content", []):
                ecli, node = self._build_content_node(raw_entry)
                if ecli and node:
                    writer.add(node)
                    judgments_by_ecli[ecli] = node

        logger.info("Created %d Rechtspraak judgment nodes.", len(judgments_by_ecli))

        # Create lightweight ECLI stub nodes from index records.
        index_records = raw.get("index", [])

        # Collect candidate (ecli, key) pairs, skipping ECLIs already written as
        # full content nodes in this same run (those are definitely not stubs).
        stub_candidates: list[tuple[str, str]] = []
        for raw_entry in index_records:
            meta = self._meta(raw_entry)
            ecli = meta.get("ecli")
            if not ecli:
                continue
            if ecli in judgments_by_ecli:
                continue
            stub_candidates.append((ecli, make_node_key(ecli)))

        # Bulk-fetch keys of existing non-stub nodes so we don't overwrite them.
        non_stub_keys: set[str] = set()
        if stub_candidates:
            candidate_keys = [key for _ecli, key in stub_candidates]
            aql = f"""
FOR doc IN {COLLECTION_JUDGMENTS}
  FILTER doc._key IN @keys AND (doc.props.stub == null OR doc.props.stub == false)
  RETURN doc._key
"""
            non_stub_keys = cast(
                set[str], set(self.store.query(aql, {"keys": candidate_keys}))
            )

        # Build and batch-upsert stub documents.
        stub_docs: list[dict] = []
        for ecli, key in stub_candidates:
            if key in non_stub_keys:
                continue
            stub_node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=key,
                labels=["Rechtspraak", "Stub"],
                props={
                    "source": SOURCE_RECHTSPRAAK,
                    "ecli": ecli,
                    "stub": True,
                    "display_name": ecli,
                },
            )
            stub_docs.append(stub_node.to_document())

        stubs_created = 0
        for batch_start in range(0, len(stub_docs), 200):
            batch = stub_docs[batch_start : batch_start + 200]
            created, updated = self.store.bulk_insert_or_update_nodes(
                COLLECTION_JUDGMENTS, batch
            )
            stubs_created += created

        logger.info(
            "Created/updated %d Rechtspraak ECLI stub nodes from index records.",
            stubs_created,
        )

        return {
            "judgments_by_ecli": judgments_by_ecli,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """No structural edges to build for Rechtspraak judgments."""
        return 0
