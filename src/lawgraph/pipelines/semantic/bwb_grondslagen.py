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

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_DELEGATED_BY,
    SOURCE_BWB,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.pipelines.normalize._xml import local_name as _local

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-grondslagen-linker"


@dataclass
class GrondslagenNeeds:
    """Collected data needed to build DELEGATED_BY edges for one pipeline run."""

    parsed_rows: list[tuple[str, list[dict[str, Any]]]] = field(default_factory=list)
    instrument_keys: set[str] = field(default_factory=set)
    article_keys: set[str] = field(default_factory=set)
    article_pairs: set[tuple[str, str]] = field(default_factory=set)


# Matches "artikel 5", "art. 3a", "artikelen 6 tot en met 9" etc.
_ARTIKEL_PATTERN = re.compile(r"\bartikel(?:en)?\s+(\d+[a-zA-Z]*)", re.IGNORECASE)
# Matches BWB-IDs in extref attributes or text: BWBR0012345
_BWBR_PATTERN = re.compile(r"BWBR\d{7}", re.IGNORECASE)


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

    def _collect_grondslagen_needs(self, result: PipelineResult) -> GrondslagenNeeds:
        """Fetch toestand XML records, parse grondslagen, and collect lookup needs."""
        aql = """
FOR rs IN raw_sources
  FILTER rs.source == @source
  FILTER rs.kind == 'bwb-toestand-xml'
  FILTER rs.payload_text != null
  RETURN {
    bwb_id: rs.identifier,
    xml: rs.payload_text
  }
"""
        try:
            rows = list(self.store.query(aql, {"source": SOURCE_BWB}))
        except Exception as exc:
            logger.warning("BWB grondslagen: query failed: %s", exc)
            return GrondslagenNeeds()

        if not rows:
            logger.debug("BWB grondslagen: no toestand XML records found.")
            return GrondslagenNeeds()

        logger.info("BWB grondslagen: processing %d toestand XML records.", len(rows))

        needs = GrondslagenNeeds()

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

            needs.parsed_rows.append((bwb_id, grondslagen))
            needs.instrument_keys.add(make_node_key(bwb_id))

            for grondslag in grondslagen:
                bwb_ref = grondslag["bwb_ref"]
                article_labels = grondslag["article_labels"]
                if not bwb_ref or not article_labels:
                    continue
                for label in article_labels:
                    needs.article_keys.add(make_node_key(bwb_ref, label))
                    needs.article_pairs.add((bwb_ref, label))

        return needs

    def _bulk_load_instruments(
        self, needed_instrument_keys: set[str]
    ) -> dict[str, dict[str, Any]]:
        """Bulk-load instrument docs by node key. Returns key → doc mapping."""
        instrument_cache: dict[str, dict[str, Any]] = {}
        if not needed_instrument_keys:
            return instrument_cache

        inst_aql = """
FOR inst IN instruments
  FILTER inst._key IN @keys
  RETURN inst
"""
        try:
            for doc in self.store.query(
                inst_aql, {"keys": list(needed_instrument_keys)}
            ):
                instrument_cache[doc["_key"]] = doc
        except Exception as exc:
            logger.warning("BWB grondslagen: instrument bulk lookup failed: %s", exc)

        return instrument_cache

    def _bulk_load_articles(
        self,
        needed_article_keys: set[str],
        needed_article_pairs: set[tuple[str, str]],
    ) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
        """Bulk-load article docs by exact key and by (bwb_ref, label) fallback.

        Returns:
            article_cache: _key → doc (exact-key matches)
            article_pair_cache: (bwb_ref, label) → doc (fallback matches)
        """
        article_cache: dict[str, dict[str, Any]] = {}
        if needed_article_keys:
            art_aql = """
FOR art IN instrument_articles
  FILTER art._key IN @keys
  RETURN art
"""
            try:
                for doc in self.store.query(
                    art_aql, {"keys": list(needed_article_keys)}
                ):
                    article_cache[doc["_key"]] = doc
            except Exception as exc:
                logger.warning("BWB grondslagen: article bulk lookup failed: %s", exc)

        missing_pairs = {
            (bwb_ref, label)
            for bwb_ref, label in needed_article_pairs
            if make_node_key(bwb_ref, label) not in article_cache
        }
        article_pair_cache: dict[tuple[str, str], dict[str, Any]] = {}
        if missing_pairs:
            missing_bwb_ids = list({bwb_ref for bwb_ref, _ in missing_pairs})
            missing_labels = list({label for _, label in missing_pairs})
            art_fallback_aql = """
FOR art IN instrument_articles
  FILTER art.props.bwb_id IN @bwb_ids
  FILTER art.props.label IN @labels OR art.props.article_number IN @labels
  RETURN art
"""
            try:
                for doc in self.store.query(
                    art_fallback_aql,
                    {"bwb_ids": missing_bwb_ids, "labels": missing_labels},
                ):
                    props = doc.get("props", {})
                    bwb_id_prop = (props.get("bwb_id") or "").upper()
                    for lbl_field in ("label", "article_number"):
                        lbl_val = props.get(lbl_field) or ""
                        pair = (bwb_id_prop, str(lbl_val))
                        if pair in missing_pairs and pair not in article_pair_cache:
                            article_pair_cache[pair] = doc
            except Exception as exc:
                logger.warning(
                    "BWB grondslagen: article fallback lookup failed: %s", exc
                )

        return article_cache, article_pair_cache

    def _build_edges(
        self,
        result: PipelineResult,
        parsed_rows: list[tuple[str, list[dict[str, Any]]]],
        instruments: dict[str, dict[str, Any]],
        articles: dict[str, dict[str, Any]],
        article_pairs: dict[tuple[str, str], dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Build DELEGATED_BY edge docs from parsed grondslagen using in-memory lookups.

        Returns the edge batch and the count of successfully processed AMvB records.
        """
        edge_batch: list[dict[str, Any]] = []
        processed = 0

        for bwb_id, grondslagen in parsed_rows:
            amvb_key = make_node_key(bwb_id)
            amvb_doc = instruments.get(amvb_key)
            if not amvb_doc:
                result.skipped += 1
                continue

            amvb_node = Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=amvb_doc["_key"],
                props=amvb_doc.get("props", {}),
                _skip_validation=True,
            )

            for grondslag in grondslagen:
                bwb_ref = grondslag["bwb_ref"]
                article_labels = grondslag["article_labels"]
                raw_text = grondslag["raw_text"]

                if not bwb_ref or not article_labels:
                    continue

                for label in article_labels:
                    article_key = make_node_key(bwb_ref, label)
                    art_doc = articles.get(article_key) or article_pairs.get(
                        (bwb_ref, label)
                    )
                    if not art_doc:
                        continue

                    art_node = Node(
                        collection=COLLECTION_INSTRUMENT_ARTICLES,
                        type=NodeType.ARTICLE,
                        key=art_doc["_key"],
                        props=art_doc.get("props", {}),
                        _skip_validation=True,
                    )

                    edge_doc = self._make_edge_doc(
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
                    )
                    if edge_doc:
                        edge_batch.append(edge_doc)

            processed += 1

        return edge_batch, processed

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        needs = self._collect_grondslagen_needs(result)
        if not needs.parsed_rows:
            return result

        instruments = self._bulk_load_instruments(needs.instrument_keys)
        articles, article_pairs = self._bulk_load_articles(
            needs.article_keys, needs.article_pairs
        )
        edge_batch, processed = self._build_edges(
            result, needs.parsed_rows, instruments, articles, article_pairs
        )

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info(
            "BWB grondslagen: processed %d records, %s.", processed, result.summary()
        )
        return result
