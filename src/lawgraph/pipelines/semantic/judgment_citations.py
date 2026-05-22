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
from lawgraph.core.time import describe_since, iso_timestamp

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

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        pending, all_cited_eclis, doc_count = self._collect_references(since)
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

        ecli_to_id = self._resolve_eclis(all_cited_eclis)
        self._emit_edges(pending, ecli_to_id, result)
        logger.info("Judgment citation linker: %s.", result.summary())
        return result

    def _collect_references(
        self, since: dt.datetime | None
    ) -> tuple[list[tuple[str, str]], set[str], int]:
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
            if not judgment.arango_id:
                continue
            for ecli in eclis:
                if ecli == source_ecli:
                    continue
                pending.append((judgment.arango_id, ecli))
                all_cited_eclis.add(ecli)
        return pending, all_cited_eclis, doc_count

    def _resolve_eclis(self, all_cited_eclis: set[str]) -> dict[str, str]:
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
            if node and node.arango_id:
                ecli_to_id[ecli] = node.arango_id
        return ecli_to_id

    def _emit_edges(
        self,
        pending: list[tuple[str, str]],
        ecli_to_id: dict[str, str],
        result: PipelineResult,
    ) -> None:
        edge_batch: list[dict[str, Any]] = []
        for from_id, cited_ecli in pending:
            to_id = ecli_to_id.get(cited_ecli)
            if not to_id:
                continue
            from_coll, from_key = from_id.split("/", 1)
            to_coll, to_key = to_id.split("/", 1)
            from_node = Node(
                collection=from_coll, type=NodeType.JUDGMENT, key=from_key, props={}
            )
            to_node = Node(
                collection=to_coll, type=NodeType.JUDGMENT, key=to_key, props={}
            )
            edge_doc = self._make_edge_doc(
                from_node=from_node,
                to_node=to_node,
                relation=RELATION_CITES_JUDGMENT,
                source=SEMANTIC_SOURCE,
                confidence=0.95,
                meta={"cited_ecli": cited_ecli},
                status=EDGE_STATUS_CANONIEK,
            )
            if edge_doc:
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

    def _load_judgments(
        self, since: dt.datetime | None = None
    ) -> Iterable[dict[str, Any]]:
        if since is not None:
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
