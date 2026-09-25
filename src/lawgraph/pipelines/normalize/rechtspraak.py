from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.judgments import (
    case_number_keys,
    compose_display_name,
    derive_court_tier,
    extract_judgment_text,
    extract_rdf_metadata,
    extract_sections,
    parse_judgment,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

RAW_BATCH_SIZE = 200


class RechtspraakNormalizePipeline(NormalizePipelineBase):
    """Normalization pipeline that turns Rechtspraak raw dumps into judgment nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, Iterator[dict[str, Any]]]:
        """The Rechtspraak content raw_sources records, streamed in small batches.

        A judgment is tens of KB of XML and a run holds tens of thousands: the records are
        read as they are normalized, not loaded first.
        """
        return {
            "content": self._iter_raw_sources(
                source=SOURCE_RECHTSPRAAK,
                kinds=[RAW_KIND_RS_CONTENT],
                since=since,
                batch_size=RAW_BATCH_SIZE,
            )
        }

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

        try:
            root = parse_judgment(payload_text)  # once, for the three extractors below
        except ValueError as exc:
            self._unreadable.append(f"{ecli} ({exc})")
            return None, None

        props: dict[str, Any] = {
            "source": SOURCE_RECHTSPRAAK,
            "ecli": ecli,
        }
        if raw_entry.get("kind"):
            props["source_kind"] = raw_entry["kind"]
        if meta:
            props["meta"] = meta

        summary, text = extract_judgment_text(root)
        if summary:
            props["summary"] = summary
        if text:
            props["text"] = text

        judgment_meta, subjects = extract_rdf_metadata(root)
        if judgment_meta:
            props["judgment_metadata"] = judgment_meta
            for field in ("court", "date", "case_number"):
                if field in judgment_meta:
                    props[field] = judgment_meta[field]
            for field in ("related_eclis", "conclusion_eclis"):
                if judgment_meta.get(field):
                    props[field] = judgment_meta[field]
            if keys := case_number_keys(judgment_meta.get("case_number")):
                props["case_number_keys"] = keys
        if subjects:
            props["subjects"] = subjects

        sections = extract_sections(root)
        if sections:
            props["paragraphs"] = sections

        court_code, tier = derive_court_tier(ecli, props.get("court"))
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
        raw: dict[str, Iterator[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Convert Rechtspraak content payloads into judgment nodes, one batch at a time."""
        count = 0
        self._unreadable: list[str] = []
        with NodeWriter(self.store) as writer:
            for raw_entry in raw.get("content", []):
                ecli, node = self._build_content_node(raw_entry)
                if ecli and node:
                    writer.add(node)
                    count += 1
                else:
                    result.skipped += 1

        if self._unreadable:
            logger.warning(
                "%d judgment(s) whose stored XML cannot be read were left out (first: %s); "
                "`retrieve rechtspraak --ecli` fetches one again.",
                len(self._unreadable),
                self._unreadable[0],
            )
        logger.info("Created %d Rechtspraak judgment nodes.", count)
        return {"judgments": count}

    def build_edges(
        self,
        raw: dict[str, Iterator[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> None:
        """No structural edges to build for Rechtspraak judgments."""
