"""Semantic pipeline: kamerstukdossier → RESULTED_IN → BWB instrument.

Matches closed/aangenomen kamerstukdossiers to the BWB law they produced by:
  1. Comparing the dossier citeertitel against instrument citation_title / title
  2. Following RAAKT edges from the dossier to candidate instruments
  3. Checking if the dossier's titel matches a BWB instrument's citation_title

Only creates edges for dossiers with outcome=='aangenomen' or where the
Citeertitel exactly matches a BWB instrument.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    COLLECTION_KAMERSTUKDOSSIERS,
    RELATION_RAAKT,
    RELATION_RESULTED_IN,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import iso_timestamp

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "dossier-law-linker"

_CONFIDENCE_BY_MATCH_TYPE: dict[str, float] = {
    "citation_title": 0.90,
    "raakt_title": 0.65,
}

# Strategy 1: exact citeertitel match — dossier.props.titel → instrument.props.citation_title
_AQL_CITE = """
FOR dos IN kamerstukdossiers
  FILTER dos.props.afgedaan == true OR dos.props.outcome == 'aangenomen'
  FILTER dos.props.titel != null AND LENGTH(dos.props.titel) > 5
  {since_filter}
  FOR inst IN instruments
    FILTER inst.props.citation_title != null
    FILTER LOWER(TRIM(dos.props.titel)) == LOWER(TRIM(inst.props.citation_title))
    LIMIT 1000
    RETURN {{
      dos_id: dos._id,
      dos_key: dos._key,
      inst_id: inst._id,
      inst_key: inst._key,
      match_type: 'citation_title'
    }}
"""

# Strategy 2: RAAKT edges from dossier to instrument + title similarity
_AQL_RAAKT = """
FOR dos IN kamerstukdossiers
  FILTER dos.props.afgedaan == true OR dos.props.outcome == 'aangenomen'
  FILTER dos.props.titel != null AND LENGTH(dos.props.titel) > 5
  {since_filter}
  FOR e IN edges
    FILTER e._from == dos._id AND e.relation == @raakt
    FOR inst IN instruments
      FILTER inst._id == e._to
      FILTER inst.props.bwb_id != null
      FILTER inst.props.citation_title != null
          OR (inst.props.title != null AND CONTAINS(
                  LOWER(dos.props.titel), LOWER(SPLIT(inst.props.title, '(')[0])
              ))
      LIMIT 1000
      RETURN {{
        dos_id: dos._id,
        dos_key: dos._key,
        inst_id: inst._id,
        inst_key: inst._key,
        match_type: 'raakt_title'
      }}
"""


class DossierLawLinkPipeline(SemanticPipelineBase):
    """Links aangenomen kamerstukdossiers to their resulting BWB instrument."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        since_filter = (
            "FILTER dos.props.geopend_op >= @since_iso OR dos.props.gesloten_op >= @since_iso"
            if since
            else ""
        )
        aql_cite = _AQL_CITE.format(since_filter=since_filter)
        aql_raakt = _AQL_RAAKT.format(since_filter=since_filter)

        cite_vars: dict[str, Any] = {}
        raakt_vars: dict[str, Any] = {"raakt": RELATION_RAAKT}
        if since:
            since_iso = iso_timestamp(since)
            cite_vars["since_iso"] = since_iso
            raakt_vars["since_iso"] = since_iso

        rows: list[dict[str, Any]] = []
        for aql, bvars in ((aql_cite, cite_vars or None), (aql_raakt, raakt_vars)):
            try:
                rows.extend(self.store.query(aql, bvars))
            except Exception as exc:
                logger.warning("DossierLawLink semantic query failed: %s", exc)

        if not rows:
            logger.debug(
                "DossierLawLink: no aangenomen dossiers found with matching instruments."
            )
            return result

        logger.info(
            "DossierLawLink: processing %d dossier-instrument pairs.", len(rows)
        )

        seen: set[tuple[str, str]] = set()

        for row in rows:
            dos_id = row.get("dos_id")
            dos_key = row.get("dos_key")
            inst_id = row.get("inst_id")
            inst_key = row.get("inst_key")
            match_type = row.get("match_type", "citation_title")

            if not dos_id or not inst_id:
                result.skipped += 1
                continue

            pair = (dos_id, inst_id)
            if pair in seen:
                continue
            seen.add(pair)

            if match_type not in _CONFIDENCE_BY_MATCH_TYPE:
                logger.warning(
                    "DossierLawLink: unknown match_type %r — skipping.", match_type
                )
                continue
            confidence = _CONFIDENCE_BY_MATCH_TYPE[match_type]

            dos_node = Node(
                collection=COLLECTION_KAMERSTUKDOSSIERS,
                type=NodeType.DOSSIER,
                key=dos_key,
                props={},
            )
            inst_node = Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=inst_key,
                props={},
            )

            created = self._create_semantic_edge(
                from_node=dos_node,
                to_node=inst_node,
                relation=RELATION_RESULTED_IN,
                source=SEMANTIC_SOURCE,
                confidence=confidence,
                meta={"match_type": match_type},
                result=result,
            )
            if created:
                result.created += 1
            else:
                result.updated += 1

        logger.info("DossierLawLink: %s.", result.summary())
        return result
