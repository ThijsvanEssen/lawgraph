"""Semantic pipeline: AMvB instruments → DELEGATED_BY → parent law articles.

Parses ``<grondslagen>`` from BWB toestand XML stored in raw_sources and
creates DELEGATED_BY edges from the AMvB instrument to the specific article
of the parent law it derives its authority from.

<grondslagen> typically looks like:
  <grondslag>
    <al>Gebaseerd op artikel 5 van de Wet foo (Stb. 2020/123)</al>
  </grondslag>
or via child elements:
  <grondslag>
    <extref doc="BWBR0001234">artikel 5</extref>
  </grondslag>
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_DELEGATED_BY,
    SOURCE_BWB,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, PipelineResult, make_node_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-grondslagen-linker"

# Matches "artikel 5", "art. 3a", "artikelen 6 tot en met 9" etc.
_ARTIKEL_PATTERN = re.compile(r"\bartikel(?:en)?\s+(\d+[a-zA-Z]*)", re.IGNORECASE)
# Matches BWB-IDs in extref attributes or text: BWBR0012345
_BWBR_PATTERN = re.compile(r"BWBR\d{7}", re.IGNORECASE)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _extract_grondslagen(xml_text: str) -> list[dict[str, Any]]:
    """Extract grondslag entries from BWB toestand XML.

    Returns a list of dicts with keys:
      bwb_ref: str | None  — referenced BWB-ID (from extref or text)
      article_labels: list[str]  — article label strings found ("5", "3a", etc.)
      raw_text: str  — full text of the grondslag element
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results: list[dict[str, Any]] = []

    for grondslag in root.iter():
        if _local(grondslag.tag).lower() != "grondslag":
            continue

        # Collect all text (including tail text of children)
        parts: list[str] = []
        if grondslag.text:
            parts.append(grondslag.text)
        for child in grondslag:
            if child.text:
                parts.append(child.text)
            if child.tail:
                parts.append(child.tail)

        raw_text = " ".join(parts).strip()

        # Try to find a BWB-ID reference
        bwb_ref: str | None = None
        for child in grondslag.iter():
            if _local(child.tag).lower() == "extref":
                doc_attr = child.get("doc") or child.get("reeks") or ""
                m = _BWBR_PATTERN.search(doc_attr)
                if m:
                    bwb_ref = m.group(0).upper()
                    break

        if not bwb_ref:
            m = _BWBR_PATTERN.search(raw_text)
            if m:
                bwb_ref = m.group(0).upper()

        # Extract article labels
        article_labels = [m.group(1) for m in _ARTIKEL_PATTERN.finditer(raw_text)]

        if bwb_ref or article_labels:
            results.append(
                {
                    "bwb_ref": bwb_ref,
                    "article_labels": article_labels,
                    "raw_text": raw_text[:300],
                }
            )

    return results


class BWBGrondslagenSemanticPipeline(SemanticPipelineBase):
    """Creates DELEGATED_BY edges from AMvB instruments to their grondslag articles."""

    def run(self, *, since: Any = None) -> PipelineResult:
        result = PipelineResult()

        # Fetch all BWB toestand XML records that have an AMvB instrument
        aql = """
FOR rs IN raw_sources
  FILTER rs.source == @source
  FILTER rs.kind == 'bwb-toestand-xml'
  FILTER rs.payload != null
  RETURN {
    bwb_id: rs.identifier,
    xml: rs.payload
  }
"""
        try:
            rows = list(self.store.query(aql, {"source": SOURCE_BWB}))
        except Exception as exc:
            logger.warning("BWB grondslagen: query failed: %s", exc)
            return result

        if not rows:
            logger.debug("BWB grondslagen: no toestand XML records found.")
            return result

        logger.info("BWB grondslagen: processing %d toestand XML records.", len(rows))
        processed = 0

        for row in rows:
            bwb_id = (row.get("bwb_id") or "").upper()
            xml_text = row.get("xml") or ""
            if not bwb_id or not xml_text:
                result.skipped += 1
                continue

            grondslagen = _extract_grondslagen(xml_text)
            if not grondslagen:
                result.skipped += 1
                continue

            # Look up the AMvB instrument node
            amvb_key = make_node_key(bwb_id)
            amvb_aql = """
FOR inst IN instruments
  FILTER inst._key == @key
  LIMIT 1
  RETURN inst
"""
            try:
                amvb_rows = list(self.store.query(amvb_aql, {"key": amvb_key}))
            except Exception as exc:
                logger.debug(
                    "BWB grondslagen: instrument lookup failed for %s: %s", bwb_id, exc
                )
                result.skipped += 1
                continue

            if not amvb_rows:
                result.skipped += 1
                continue

            amvb_doc = amvb_rows[0]
            amvb_node = Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=amvb_doc["_key"],
                props=amvb_doc.get("props", {}),
            )

            for grondslag in grondslagen:
                bwb_ref = grondslag["bwb_ref"]
                article_labels = grondslag["article_labels"]
                raw_text = grondslag["raw_text"]

                if not bwb_ref or not article_labels:
                    continue

                for label in article_labels:
                    article_key = make_node_key(bwb_ref, label)

                    # Try to find the article node; skip if it doesn't exist
                    art_aql = """
FOR art IN instrument_articles
  FILTER art._key == @key
  LIMIT 1
  RETURN art
"""
                    try:
                        art_rows = list(self.store.query(art_aql, {"key": article_key}))
                    except Exception as exc:
                        logger.debug("BWB grondslagen: article lookup failed: %s", exc)
                        continue

                    if not art_rows:
                        # Try partial key match (article numbers are sometimes stored differently)
                        art_aql2 = """
FOR art IN instrument_articles
  FILTER art.props.bwb_id == @bwb_id
  FILTER art.props.label == @label OR art.props.article_number == @label
  LIMIT 1
  RETURN art
"""
                        try:
                            art_rows = list(
                                self.store.query(
                                    art_aql2, {"bwb_id": bwb_ref, "label": label}
                                )
                            )
                        except Exception:
                            continue

                    if not art_rows:
                        continue

                    art_doc = art_rows[0]
                    art_node = Node(
                        collection=COLLECTION_INSTRUMENT_ARTICLES,
                        type=NodeType.ARTICLE,
                        key=art_doc["_key"],
                        props=art_doc.get("props", {}),
                    )

                    created = self._create_semantic_edge(
                        from_node=amvb_node,
                        to_node=art_node,
                        relation=RELATION_DELEGATED_BY,
                        source=SEMANTIC_SOURCE,
                        confidence=0.90,
                        meta={
                            "grondslag_text": raw_text,
                            "parent_bwb_id": bwb_ref,
                            "article_label": label,
                        },
                        result=result,
                    )
                    if created:
                        result.created += 1
                    else:
                        result.updated += 1

            processed += 1

        logger.info(
            "BWB grondslagen: processed %d records, %s.", processed, result.summary()
        )
        return result
