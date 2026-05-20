"""Semantic pipeline that detects ECLI references between judgments (CITES_JUDGMENT)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_CANONIEK,
    RELATION_CITES_JUDGMENT,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since
from lawgraph.db import _edge_key as _sha1_edge_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-citation-linker"

# Matches ECLI:NL:HR:2020:1234 and international variants.
_ECLI_PATTERN = re.compile(
    r"\bECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:\d+\b",
    re.IGNORECASE,
)


def detect_ecli_references(text: str | None) -> list[str]:
    """Return unique ECLI identifiers found in text, normalised to upper-case."""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in _ECLI_PATTERN.finditer(text):
        ecli = match.group(0).upper()
        if ecli not in seen:
            seen.add(ecli)
            result.append(ecli)
    return result


class JudgmentCitationsSemanticPipeline(SemanticPipelineBase):
    """Detect ECLI cross-references in judgment texts and create CITES_JUDGMENT edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:  # noqa: C901
        result = PipelineResult()

        # Phase 1: stream judgments, collect (judgment_id, cited_ecli) pairs.
        # Avoids materialising the full corpus into Python heap.
        pending: list[tuple[str, str]] = []
        all_cited_eclis: set[str] = set()
        doc_count = 0

        for doc in self._load_judgments(since=since):
            judgment = Node.from_document(COLLECTION_JUDGMENTS, doc)
            text = self._extract_text(judgment)
            eclis = detect_ecli_references(text)
            if not eclis:
                continue

            source_ecli = (judgment.props.get("ecli") or "").upper()
            doc_count += 1
            if not judgment.id:
                continue
            for ecli in eclis:
                if ecli == source_ecli:
                    continue
                pending.append((judgment.id, ecli))
                all_cited_eclis.add(ecli)

        if not pending:
            logger.debug(
                "No ECLI cross-references found (since=%s).", describe_since(since)
            )
            return result

        logger.info(
            "Found %d ECLI references across %d judgments (since=%s).",
            len(pending),
            doc_count,
            describe_since(since),
        )

        # Phase 2: batch-resolve all cited ECLIs to node IDs in one query.
        ecli_to_id: dict[str, str] = {}
        aql = f"""
        FOR doc IN {COLLECTION_JUDGMENTS}
            FILTER doc.props.ecli IN @eclis
            RETURN {{ ecli: doc.props.ecli, id: doc._id }}
        """
        for row in self.store.query(aql, bind_vars={"eclis": list(all_cited_eclis)}):
            ecli_val = (row.get("ecli") or "").upper()
            node_id = row.get("id") or ""
            if ecli_val and node_id:
                ecli_to_id[ecli_val] = node_id

        # Create stubs for ECLIs not yet in the corpus.
        for ecli in all_cited_eclis:
            if ecli in ecli_to_id:
                continue
            key = make_node_key(ecli)
            node = self.store.ensure_stub_node(
                COLLECTION_JUDGMENTS,
                key,
                NodeType.JUDGMENT,
                props={"ecli": ecli},
            )
            if node and node.id:
                ecli_to_id[ecli] = node.id

        # Phase 3: build and flush edge docs in one batch AQL call.
        edge_batch: list[dict[str, Any]] = []

        for from_id, cited_ecli in pending:
            to_id = ecli_to_id.get(cited_ecli)
            if not to_id:
                continue
            edge_doc: dict[str, Any] = {
                "_key": _sha1_edge_key(from_id, RELATION_CITES_JUDGMENT, to_id),
                "_from": from_id,
                "_to": to_id,
                "relation": RELATION_CITES_JUDGMENT,
                "confidence": 0.95,
                "source": SEMANTIC_SOURCE,
                "status": EDGE_STATUS_CANONIEK,
                "meta": {"cited_ecli": cited_ecli},
            }
            edge_batch.append(edge_doc)
            if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                created, updated = self._flush_edge_batch(edge_batch, result)
                result.created += created
                result.updated += updated
                edge_batch = []

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info("Judgment citation linker: %s.", result.summary())
        return result

    def _load_judgments(
        self, since: dt.datetime | None = None
    ) -> Iterable[dict[str, Any]]:
        if since is not None:
            from lawgraph.core.time import iso_timestamp

            since_iso = iso_timestamp(since)
            aql = f"""
            FOR doc IN {COLLECTION_JUDGMENTS}
                FILTER doc.props.fetched_at >= @since
                RETURN doc
            """
            return self.store.query(aql, bind_vars={"since": since_iso})
        return self.store.query(f"FOR doc IN {COLLECTION_JUDGMENTS} RETURN doc")

    def _extract_text(self, judgment: Node) -> str | None:
        return self._extract_props_text(judgment.props, "raw_xml", "text", "body")
