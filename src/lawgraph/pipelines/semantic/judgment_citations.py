"""Semantic pipeline that detects ECLI references between judgments (REFERS_TO)."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    EDGE_STATUS_CANONIEK,
    RELATION_REFERS_TO,
)
from lawgraph.core.identifiers import find_eclis
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-citation-linker"


class JudgmentCitationsSemanticPipeline(SemanticPipelineBase):
    """Detect ECLI cross-references in judgment texts and create REFERS_TO edges."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        pending, all_cited_eclis, doc_count = self._collect_references()
        if not pending:
            logger.debug("No ECLI cross-references found.")
            return result

        logger.info(
            "Found %d ECLI references across %d judgments.",
            len(pending),
            doc_count,
        )

        ecli_to_id = self._resolve_eclis(all_cited_eclis)
        self._emit_edges(pending, ecli_to_id, result)
        logger.info("Judgment citation linker: %s.", result.summary())
        return result

    def _collect_references(self) -> tuple[list[tuple[str, str]], set[str], int]:
        pending: list[tuple[str, str]] = []
        all_cited_eclis: set[str] = set()
        doc_count = 0
        for judgment, xml in self._judgment_texts():
            eclis = find_eclis(xml)
            if not eclis:
                continue
            source_ecli = str(judgment.props["ecli"]).upper()
            doc_count += 1
            if not judgment.arango_id:
                continue
            for ecli in eclis:
                if ecli == source_ecli:
                    continue
                pending.append((judgment.arango_id, ecli))
                all_cited_eclis.add(ecli)
        return pending, all_cited_eclis, doc_count

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
                relation=RELATION_REFERS_TO,
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
