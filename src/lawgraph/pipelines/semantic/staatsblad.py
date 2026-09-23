"""Semantic pipeline: links Staatsblad NvT documents to instruments via EXPLAINS."""

from __future__ import annotations

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, collection_from_id
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

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

        rows = semantic_queries.staatsblad_instrument_matches(self.store)

        if not rows:
            logger.debug("No Staatsblad NvT documents found for EXPLAINS linking.")
            return result

        logger.info(
            "Staatsblad NvT semantic linker: processing %d publication-instrument pairs.",
            len(rows),
        )

        # Deduplicate by (pub_id, inst_id)
        seen: set[tuple[str, str]] = set()
        edges = EdgeWriter(self.store, what=None)

        for row in self._track(rows, "publications", total=len(rows)):
            pub_id = row.get("pub_id")
            pub_key = row.get("pub_key")
            inst_id = row.get("inst_id")
            inst_key = row.get("inst_key")
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

            pub_collection = collection_from_id(pub_id, COLLECTION_DOCUMENTS)
            inst_collection = collection_from_id(inst_id, COLLECTION_INSTRUMENTS)

            pub_node = Node(
                collection=pub_collection,
                type=NodeType.DOCUMENT,
                key=pub_key,
                props={},
            )
            inst_node = Node(
                collection=inst_collection,
                type=NodeType.INSTRUMENT,
                key=inst_key,
                props={},
            )

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
        return result
