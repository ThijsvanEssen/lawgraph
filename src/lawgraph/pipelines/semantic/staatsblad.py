"""Semantic pipeline: links Staatsblad NvT documents to instruments via EXPLAINS.

Derived in full on every run: an edge no publication supports any more goes.
"""

from __future__ import annotations

from lawgraph.config.constants import (
    RELATION_EXPLAINS,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, parse_node_id
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "staatsblad-nvt-linker"

_CONFIDENCE_BY_MATCH_TYPE: dict[str, float] = {
    "bwb_id": 0.85,
    "title": 0.60,
}


class StaatsbladSemanticPipeline(SemanticPipelineBase):
    """Pipeline linking Staatsblad NvT documents to BWB instruments via EXPLAINS."""

    def run(self) -> PipelineResult:
        result = PipelineResult()

        rows = semantic_bwb.staatsblad_instrument_matches(self.store)
        logger.info(
            "Staatsblad NvT semantic linker: processing %d publication-instrument pairs.",
            len(rows),
        )

        # Deduplicate by (pub_id, inst_id)
        seen: set[tuple[str, str]] = set()
        edges = EdgeWriter(self.store, what=None, remembers=True)

        for row in self._track(rows, "publications", total=len(rows)):
            pub_id = row.get("pub_id")
            inst_id = row.get("inst_id")
            match_type = row.get("match_type", "bwb_id")

            if not pub_id or not inst_id:
                result.skipped += 1
                continue

            pair = (pub_id, inst_id)
            if pair in seen:
                continue
            seen.add(pair)

            if match_type not in _CONFIDENCE_BY_MATCH_TYPE:
                raise ValueError(f"Unknown match_type: {match_type!r}")
            confidence = _CONFIDENCE_BY_MATCH_TYPE[match_type]

            pub_node = Node.skeleton(*parse_node_id(pub_id))
            inst_node = Node.skeleton(*parse_node_id(inst_id))

            edges.add_doc(
                self._make_edge_doc(
                    from_node=pub_node,
                    to_node=inst_node,
                    relation=RELATION_EXPLAINS,
                    source=SEMANTIC_SOURCE,
                    confidence=confidence,
                    meta={"match_type": match_type},
                )
            )

        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_EXPLAINS, SEMANTIC_SOURCE)
        logger.info(
            "Staatsblad NvT: %d edges no publication supports removed.", removed
        )
        return result
