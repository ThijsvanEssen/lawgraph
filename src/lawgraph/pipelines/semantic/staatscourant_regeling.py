"""Semantic pipeline: Staatscourant ministeriele regelingen → EXPLAINS_INSTRUMENT.

Ministeriele regelingen almost always ground themselves explicitly in a parent
law (the grondslag). We link via three strategies, in descending confidence:

1. Explicit BWBR reference found during normalization (stored as props.bwb_id)
2. Title match: regeling title contains the instrument's citation_title
3. Text scan: regeling full text mentions a BWBR number that matches an instrument
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS_INSTRUMENT,
    SOURCE_STAATSCOURANT,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, PipelineResult

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "staatscourant-regeling-linker"
_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)


class StaatscourantRegelingSemanticPipeline(SemanticPipelineBase):
    """Links Staatscourant ministeriele regelingen to BWB instruments via EXPLAINS_INSTRUMENT."""

    def run(self, *, since: Any = None) -> PipelineResult:
        result = PipelineResult()

        # Strategy 1: explicit bwb_id stored during normalization
        aql_bwb = """
FOR pub IN publications
  FILTER pub.props.source == @source
  FILTER pub.props.bwb_id != null
  LET inst = FIRST(
    FOR i IN instruments
      FILTER UPPER(i.props.bwb_id) == UPPER(pub.props.bwb_id)
      LIMIT 1
      RETURN i
  )
  FILTER inst != null
  RETURN {
    pub_id: pub._id, pub_key: pub._key,
    inst_id: inst._id, inst_key: inst._key,
    match_type: 'bwb_id'
  }
"""

        # Strategy 2: title match against citation_title
        aql_title = """
FOR pub IN publications
  FILTER pub.props.source == @source
  FILTER pub.props.bwb_id == null
  FILTER pub.props.title != null AND LENGTH(pub.props.title) > 5
  FOR inst IN instruments
    FILTER inst.props.citation_title != null AND LENGTH(inst.props.citation_title) > 5
    FILTER CONTAINS(LOWER(pub.props.title), LOWER(inst.props.citation_title))
    LIMIT 1
    RETURN {
      pub_id: pub._id, pub_key: pub._key,
      inst_id: inst._id, inst_key: inst._key,
      match_type: 'title'
    }
"""

        bind = {"source": SOURCE_STAATSCOURANT}
        rows: list[dict[str, Any]] = []

        for aql in (aql_bwb, aql_title):
            try:
                rows.extend(self.store.query(aql, bind_vars=bind))
            except Exception as exc:
                logger.warning("Staatscourant regeling semantic query failed: %s", exc)

        # Strategy 3: BWBR pattern scan on full text (for publications not yet matched)
        already_matched_pubs = {r["pub_id"] for r in rows}
        text_rows = self._text_scan_match(already_matched_pubs)
        rows.extend(text_rows)

        if not rows:
            logger.debug("Staatscourant regeling: no links found.")
            return result

        logger.info(
            "Staatscourant regeling: processing %d publication-instrument pairs.",
            len(rows),
        )

        seen: set[tuple[str, str]] = set()
        for row in rows:
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

            confidence = {"bwb_id": 0.92, "title": 0.65, "text_scan": 0.75}.get(
                match_type, 0.60
            )

            pub_node = Node(
                collection=pub_id.split("/")[0],
                type=NodeType.PUBLICATION,
                key=pub_key,
                props={},
            )
            inst_node = Node(
                collection=(
                    inst_id.split("/")[0] if "/" in inst_id else COLLECTION_INSTRUMENTS
                ),
                type=NodeType.INSTRUMENT,
                key=inst_key,
                props={},
            )

            created = self._create_semantic_edge(
                from_node=pub_node,
                to_node=inst_node,
                relation=RELATION_EXPLAINS_INSTRUMENT,
                source=SEMANTIC_SOURCE,
                confidence=confidence,
                meta={"match_type": match_type},
                result=result,
            )
            if created:
                result.created += 1
            else:
                result.updated += 1

        logger.info("Staatscourant regeling semantic: %s.", result.summary())
        return result

    def _text_scan_match(self, already_matched: set[str]) -> list[dict[str, Any]]:
        """Find BWBR IDs in regeling text and match to instruments."""
        aql = """
FOR pub IN publications
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 100
  RETURN { pub_id: pub._id, pub_key: pub._key, text: pub.props.text }
"""
        results: list[dict[str, Any]] = []
        try:
            pubs = list(self.store.query(aql, {"source": SOURCE_STAATSCOURANT}))
        except Exception as exc:
            logger.debug("Staatscourant text scan query failed: %s", exc)
            return results

        for pub in pubs:
            pub_id = pub.get("pub_id")
            if pub_id in already_matched:
                continue
            text = pub.get("text") or ""
            bwb_ids = {m.group(1).upper() for m in _BWBR_PATTERN.finditer(text)}
            for bwb_id in bwb_ids:
                inst_aql = """
FOR inst IN instruments
  FILTER UPPER(inst.props.bwb_id) == @bwb_id
  LIMIT 1
  RETURN { inst_id: inst._id, inst_key: inst._key }
"""
                try:
                    inst_rows = list(self.store.query(inst_aql, {"bwb_id": bwb_id}))
                except Exception:
                    continue
                for inst_row in inst_rows:
                    results.append(
                        {
                            "pub_id": pub_id,
                            "pub_key": pub.get("pub_key"),
                            "inst_id": inst_row["inst_id"],
                            "inst_key": inst_row["inst_key"],
                            "match_type": "text_scan",
                        }
                    )

        return results
