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

from lawgraph.config.constants import COLLECTION_JUDGMENTS, RELATION_APPEAL_OF
from lawgraph.core.logging import get_logger
from lawgraph.core.models import (
    Node,
    NodeType,
    PipelineResult,
    make_node_key,
    parse_arango_id,
)
from lawgraph.core.time import iso_timestamp

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-appeal-linker"

_APPEAL_PATTERN = re.compile(r"\b(?:hoger beroep|cassatie)\b", re.IGNORECASE)


class JudgmentAppealPipeline(SemanticPipelineBase):
    """Create APPEAL_OF edges from appeal judgments to their prior proceedings."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        since_filter = ""
        bind_vars: dict[str, Any] = {}
        if since is not None:
            since_filter = "FILTER j.props.created_at >= @since_iso"
            bind_vars["since_iso"] = iso_timestamp(since)

        aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.related_eclis != null
  FILTER LENGTH(j.props.related_eclis) > 0
  {since_filter}
  RETURN {{
    j_id: j._id,
    procedure_type: j.props.judgment_metadata.type,
    related_eclis: j.props.related_eclis,
  }}
"""
        rows = list(self.store.query(aql, bind_vars or None))
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
        edge_batch = self._build_edge_batch(appeal_rows, ecli_to_id)

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

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

    def _resolve_eclis(self, all_related: set[str]) -> dict[str, str]:
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
            if node and node.arango_id:
                ecli_to_id[ecli] = node.arango_id
        return ecli_to_id

    def _build_edge_batch(
        self, appeal_rows: list[dict[str, Any]], ecli_to_id: dict[str, str]
    ) -> list[dict[str, Any]]:
        edge_batch: list[dict[str, Any]] = []
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
                    edge_batch.append(edge_doc)
        return edge_batch
