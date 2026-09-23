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
    COLLECTION_INSTRUMENTS,
    RELATION_EXPLAINS,
)
from lawgraph.core.identifiers import BWB_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, collection_from_id
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "staatscourant-regeling-linker"

_CONFIDENCE_BY_MATCH_TYPE: dict[str, float] = {
    "bwb_id": 0.92,
    "title": 0.65,
    "text_scan": 0.75,
}


class StaatscourantSemanticPipeline(SemanticPipelineBase):
    """Links Staatscourant ministerial regulations to BWB instruments via EXPLAINS."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        # props.date is a date: compared with a timestamp, "2026-09-19" sorts before
        # "2026-09-19T06:00:00Z" and only the publications of today would match.
        since_date = since.date().isoformat() if since else None
        rows = semantic_queries.staatscourant_instrument_matches(self.store, since_date)

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
        edges = EdgeWriter(self.store, what=None)
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

    def _text_scan_match(
        self, already_matched: set[str], *, since: dt.datetime | None = None
    ) -> list[dict[str, Any]]:
        """Find BWBR IDs in regeling text and match to instruments."""
        since_date = since.date().isoformat() if since else None
        results: list[dict[str, Any]] = []

        # Collect all (pub, bwb_id) pairs first, then batch-resolve instruments. The texts
        # stream from the cursor; only the ids are kept.
        pub_bwb_pairs: list[tuple[str, str, str]] = []  # (pub_id, pub_key, bwb_id)
        all_bwb_ids: set[str] = set()
        publications = semantic_queries.staatscourant_texts(self.store, since_date)
        for pub in self._track(publications, "publications"):
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
        bwb_to_inst: dict[str, dict[str, str]] = {}
        for inst_row in semantic_queries.instrument_ids_by_bwb_id(
            self.store, list(all_bwb_ids)
        ):
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
