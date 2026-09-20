"""Semantic pipeline: Staatscourant ministerial regulations → EXPLAINS.

Ministeriele regelingen almost always ground themselves explicitly in a parent
law (the grondslag). We link via three strategies, in descending confidence:

1. Explicit BWBR reference found during normalization (stored as props.bwb_id)
2. Title match: regeling title contains the instrument's citation_title
3. Text scan: regeling full text mentions a BWBR number that matches an instrument
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.identifiers import BWB_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, collection_from_id
from lawgraph.core.time import iso_timestamp

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "staatscourant-regeling-linker"

_CONFIDENCE_BY_MATCH_TYPE: dict[str, float] = {
    "bwb_id": 0.92,
    "title": 0.65,
    "text_scan": 0.75,
}


class StaatscourantRegelingSemanticPipeline(SemanticPipelineBase):
    """Links Staatscourant ministerial regulations to BWB instruments via EXPLAINS."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        since_filter = "FILTER pub.props.date >= @since_iso" if since else ""

        # Strategy 1: explicit bwb_id stored during normalization
        aql_bwb = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.bwb_id != null
  {since_filter}
  LET inst = FIRST(
    FOR i IN {COLLECTION_INSTRUMENTS}
      // != null lets the sparse index on props.bwb_id serve the join (else: a full scan)
      FILTER i.props.bwb_id != null AND i.props.bwb_id == pub.props.bwb_id
      LIMIT 1
      RETURN i
  )
  FILTER inst != null
  RETURN {{
    pub_id: pub._id, pub_key: pub._key,
    inst_id: inst._id, inst_key: inst._key,
    match_type: 'bwb_id'
  }}
"""

        # Strategy 2: title match against citation_title
        aql_title = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.bwb_id == null
  FILTER pub.props.title != null AND LENGTH(pub.props.title) > 5
  {since_filter}
  LET inst = FIRST(
    FOR i IN {COLLECTION_INSTRUMENTS}
      FILTER i.props.citation_title != null AND LENGTH(i.props.citation_title) > 5
      FILTER CONTAINS(LOWER(pub.props.title), LOWER(i.props.citation_title))
      LIMIT 1
      RETURN i
  )
  FILTER inst != null
  RETURN {{
    pub_id: pub._id, pub_key: pub._key,
    inst_id: inst._id, inst_key: inst._key,
    match_type: 'title'
  }}
"""

        bind: dict[str, Any] = {"source": SOURCE_STAATSCOURANT}
        if since:
            bind["since_iso"] = iso_timestamp(since)
        rows: list[dict[str, Any]] = []

        for aql in (aql_bwb, aql_title):
            try:
                rows.extend(self.store.query(aql, bind_vars=bind))
            except Exception as exc:
                logger.warning("Staatscourant regeling semantic query failed: %s", exc)

        # Strategy 3: BWBR pattern scan on full text (for publications not yet matched)
        already_matched_pubs = {r["pub_id"] for r in rows}
        text_rows = self._text_scan_match(already_matched_pubs, since=since)
        rows.extend(text_rows)

        if not rows:
            logger.debug("Staatscourant regeling: no links found.")
            return result

        logger.info(
            "Staatscourant regeling: processing %d publication-instrument pairs.",
            len(rows),
        )

        seen: set[tuple[str, str]] = set()
        edge_batch: list[dict[str, Any]] = []
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

            if match_type not in _CONFIDENCE_BY_MATCH_TYPE:
                raise ValueError(f"Unknown match_type: {match_type!r}")
            confidence = _CONFIDENCE_BY_MATCH_TYPE[match_type]

            pub_node = Node(
                collection=collection_from_id(pub_id, "documents"),
                type=NodeType.DOCUMENT,
                key=pub_key,
                props={},
            )
            inst_node = Node(
                collection=collection_from_id(inst_id, COLLECTION_INSTRUMENTS),
                type=NodeType.INSTRUMENT,
                key=inst_key,
                props={},
            )

            self._queue_edge(
                edge_batch,
                self._make_edge_doc(
                    from_node=pub_node,
                    to_node=inst_node,
                    relation=RELATION_EXPLAINS,
                    source=SEMANTIC_SOURCE,
                    confidence=confidence,
                    meta={"match_type": match_type},
                ),
                result,
            )

        self._write_batch(edge_batch, result)
        logger.info("Staatscourant regeling semantic: %s.", result.summary())
        return result

    def _text_scan_match(
        self, already_matched: set[str], *, since: dt.datetime | None = None
    ) -> list[dict[str, Any]]:
        """Find BWBR IDs in regeling text and match to instruments."""
        since_filter = "FILTER pub.props.date >= @since_iso" if since else ""
        aql = f"""
FOR pub IN {COLLECTION_DOCUMENTS}
  FILTER pub.props.source == @source
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 100
  {since_filter}
  RETURN {{ pub_id: pub._id, pub_key: pub._key, text: pub.props.text }}
"""
        bind: dict[str, Any] = {"source": SOURCE_STAATSCOURANT}
        if since:
            bind["since_iso"] = iso_timestamp(since)
        results: list[dict[str, Any]] = []

        # Collect all (pub, bwb_id) pairs first, then batch-resolve instruments. The texts
        # stream from the cursor; only the ids are kept.
        pub_bwb_pairs: list[tuple[str, str, str]] = []  # (pub_id, pub_key, bwb_id)
        all_bwb_ids: set[str] = set()
        for pub in self.store.query(aql, bind):
            pub_id = pub.get("pub_id")
            if pub_id in already_matched:
                continue
            text = pub.get("text") or ""
            bwb_ids = {m.group(1).upper() for m in BWB_ID_PATTERN.finditer(text)}
            for bwb_id in bwb_ids:
                pub_bwb_pairs.append((pub_id, pub.get("pub_key") or "", bwb_id))
                all_bwb_ids.add(bwb_id)

        if not all_bwb_ids:
            return results

        # Single batch query to resolve all bwb_ids to instruments.
        inst_aql = f"""
FOR inst IN {COLLECTION_INSTRUMENTS}
  FILTER inst.props.bwb_id IN @bwb_ids
  RETURN {{ bwb_id: inst.props.bwb_id, inst_id: inst._id, inst_key: inst._key }}
"""
        bwb_to_inst: dict[str, dict[str, str]] = {}
        for inst_row in self.store.query(inst_aql, {"bwb_ids": list(all_bwb_ids)}):
            bwb_key = inst_row.get("bwb_id") or ""
            if bwb_key and bwb_key not in bwb_to_inst:
                bwb_to_inst[bwb_key] = inst_row

        for pub_id, pub_key, bwb_id in pub_bwb_pairs:
            inst_row = bwb_to_inst.get(bwb_id)
            if not inst_row:
                continue
            results.append(
                {
                    "pub_id": pub_id,
                    "pub_key": pub_key,
                    "inst_id": inst_row["inst_id"],
                    "inst_key": inst_row["inst_key"],
                    "match_type": "text_scan",
                }
            )

        return results
