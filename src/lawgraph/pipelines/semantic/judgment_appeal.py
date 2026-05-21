"""Semantic pipeline: APPEAL_OF edges from Rechtspraak appellate case metadata.

Rechtspraak XML carries ``dcterms:relation`` (the prior-proceeding ECLI) and
``psi:procedure`` (e.g. "Hoger beroep", "Cassatie") in its RDF header.  The
normalize pipeline stores these as ``props.related_eclis`` and
``props.judgment_metadata.type`` respectively.  This pipeline reads those
fields and creates directed ``APPEAL_OF`` edges from the appeal judgment to
the prior judgment.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_APPEAL_OF,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-appeal-linker"

_APPEAL_PATTERN = re.compile(r"\b(?:hoger beroep|cassatie)\b", re.IGNORECASE)


class JudgmentAppealPipeline(SemanticPipelineBase):
    """Create APPEAL_OF edges from appeal judgments to their prior proceedings."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
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
        rows = list(self.store.query(aql))
        if not rows:
            logger.debug("No judgments with related_eclis found.")
            return result

        all_related: set[str] = set()
        appeal_rows: list[dict[str, Any]] = []
        for row in rows:
            procedure = (row.get("procedure_type") or "").strip().lower()
            if not _APPEAL_PATTERN.search(procedure):
                continue
            for ecli in row.get("related_eclis") or []:
                all_related.add(ecli.upper())
            appeal_rows.append(row)

        if not appeal_rows:
            logger.debug("No appeal-type judgments with related_eclis found.")
            return result

        logger.info(
            "Processing %d appeal judgments for APPEAL_OF edges.", len(appeal_rows)
        )

        ecli_to_id: dict[str, str] = {}
        resolve_aql = f"""
FOR doc IN {COLLECTION_JUDGMENTS}
  FILTER doc.props.ecli IN @eclis
  RETURN {{ ecli: doc.props.ecli, id: doc._id }}
"""
        for row in self.store.query(
            resolve_aql, bind_vars={"eclis": list(all_related)}
        ):
            ecli_val = (row.get("ecli") or "").upper()
            node_id = row.get("id") or ""
            if ecli_val and node_id:
                ecli_to_id[ecli_val] = node_id

        for ecli in all_related:
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

        edge_batch: list[dict[str, Any]] = []
        for row in appeal_rows:
            from_id = row["j_id"]
            from_key = from_id.split("/", 1)[-1] if "/" in from_id else from_id
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
                to_key = to_id.split("/", 1)[-1] if "/" in to_id else to_id
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
                    edge_batch.append(edge_doc)

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info("Judgment appeal linker: %s.", result.summary())
        return result
