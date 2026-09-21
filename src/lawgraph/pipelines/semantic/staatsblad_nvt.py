"""Semantic pipeline: links Staatsblad NvT documents to instruments via EXPLAINS."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, collection_from_id
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "staatsblad-nvt-linker"

_CONFIDENCE_BY_MATCH_TYPE: dict[str, float] = {
    "bwb_id": 0.85,
    "title": 0.60,
}

# Strategy 1: publications with explicit bwb_id stored during normalization
_AQL_BWB = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 50
  FILTER pub.props.bwb_id != null
  LET inst = (
    FOR i IN {COLLECTION_INSTRUMENTS}
      // != null lets the sparse index on props.bwb_id serve the join (else: a full scan)
      FILTER i.props.bwb_id != null AND i.props.bwb_id == pub.props.bwb_id
      LIMIT 1
      RETURN i
  )[0]
  FILTER inst != null
  RETURN {{ pub_id: pub._id, pub_key: pub._key, inst_id: inst._id, inst_key: inst._key,
           match_type: 'bwb_id' }}
"""

# Strategy 2: title matching for publications without bwb_id
_AQL_TITLE = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 50
  FILTER pub.props.bwb_id == null
  LET inst = (
    FOR i IN {COLLECTION_INSTRUMENTS}
      FILTER i.props.citation_title != null
      FILTER CONTAINS(LOWER(pub.props.title), LOWER(i.props.citation_title))
      LIMIT 1
      RETURN i
  )[0]
  FILTER inst != null
  RETURN {{ pub_id: pub._id, pub_key: pub._key, inst_id: inst._id, inst_key: inst._key,
           match_type: 'title' }}
"""


class StaatsbladNvtSemanticPipeline(SemanticPipelineBase):
    """Pipeline linking Staatsblad NvT documents to BWB instruments via EXPLAINS."""

    def run(self) -> PipelineResult:
        result = PipelineResult()

        bind_vars = {"source": SOURCE_STAATSBLAD}

        rows: list[dict[str, Any]] = []
        try:
            rows.extend(self.store.query(_AQL_BWB, bind_vars=bind_vars))
        except Exception as exc:
            result.add_error(f"Staatsblad NvT semantic (bwb_id query) failed: {exc}")

        try:
            rows.extend(self.store.query(_AQL_TITLE, bind_vars=bind_vars))
        except Exception as exc:
            result.add_error(f"Staatsblad NvT semantic (title query) failed: {exc}")

        if not rows:
            logger.debug("No Staatsblad NvT documents found for EXPLAINS linking.")
            return result

        logger.info(
            "Staatsblad NvT semantic linker: processing %d publication-instrument pairs.",
            len(rows),
        )

        # Deduplicate by (pub_id, inst_id)
        seen: set[tuple[str, str]] = set()
        edges = EdgeWriter(self.store)

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
        logger.info("Staatsblad NvT semantic linker: %s.", result.summary())
        return result
