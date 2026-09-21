"""Semantic pipeline: APPEAL_OF edges from Rechtspraak appellate case metadata.

Rechtspraak XML carries ``dcterms:relation`` (the prior-proceeding ECLI) and
``psi:procedure`` (e.g. "Hoger beroep", "Cassatie") in its RDF header.  The
normalize pipeline stores these as ``props.related_eclis`` and
``props.judgment_metadata.type`` respectively.  This pipeline reads those
fields and creates directed ``APPEAL_OF`` edges from the appeal judgment to
the prior judgment.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.config.constants import COLLECTION_JUDGMENTS, RELATION_APPEAL_OF
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, parse_arango_id
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "rechtspraak-appeal-linker"

_APPEAL_PATTERN = re.compile(r"\b(?:hoger beroep|cassatie)\b", re.IGNORECASE)


class RechtspraakAppealSemanticPipeline(SemanticPipelineBase):
    """Create APPEAL_OF edges from appeal judgments to their prior proceedings."""

    def run(self) -> PipelineResult:
        result = PipelineResult()

        aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.related_eclis != null
  FILTER LENGTH(j.props.related_eclis) > 0
  RETURN {{
    j_id: j._id,
    procedure_type: j.props.judgment_metadata.type,
    related_eclis: j.props.related_eclis,
  }}
"""
        rows = list(self._track(self.store.query(aql), "judgments"))
        if not rows:
            logger.debug("No judgments with related_eclis found.")
            return result

        appeal_rows, all_related = self._filter_appeal_rows(rows)
        if not appeal_rows:
            logger.debug("No appeal-type judgments with related_eclis found.")
            return result

        logger.info(
            "Processing %d appeal judgments for APPEAL_OF edges.", len(appeal_rows)
        )

        ecli_to_id = self._resolve_eclis(all_related)
        edges = EdgeWriter(self.store, what=None)
        self._link_appeals(appeal_rows, ecli_to_id, edges)
        edges.flush_into(result)

        logger.info("Judgment appeal linker: %s.", result.summary())
        return result

    def _filter_appeal_rows(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], set[str]]:
        appeal_rows: list[dict[str, Any]] = []
        all_related: set[str] = set()
        for row in rows:
            procedure = (row.get("procedure_type") or "").strip().lower()
            if not _APPEAL_PATTERN.search(procedure):
                continue
            for ecli in row.get("related_eclis") or []:
                all_related.add(ecli.upper())
            appeal_rows.append(row)
        return appeal_rows, all_related

    def _link_appeals(
        self,
        appeal_rows: list[dict[str, Any]],
        ecli_to_id: dict[str, str],
        edges: EdgeWriter,
    ) -> None:
        for row in appeal_rows:
            from_id = row["j_id"]
            _, from_key = parse_arango_id(from_id)
            procedure_type = row.get("procedure_type") or ""
            from_node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=from_key,
                props={},
            )
            for ecli in row.get("related_eclis") or []:
                to_id = ecli_to_id.get(ecli.upper())
                if not to_id:
                    continue
                _, to_key = parse_arango_id(to_id)
                to_node = Node(
                    collection=COLLECTION_JUDGMENTS,
                    type=NodeType.JUDGMENT,
                    key=to_key,
                    props={},
                )
                edge_doc = self._make_edge_doc(
                    from_node=from_node,
                    to_node=to_node,
                    relation=RELATION_APPEAL_OF,
                    source=SEMANTIC_SOURCE,
                    confidence=0.95,
                    meta={"procedure_type": procedure_type},
                )
                if edge_doc:
                    edges.add_doc(edge_doc)
