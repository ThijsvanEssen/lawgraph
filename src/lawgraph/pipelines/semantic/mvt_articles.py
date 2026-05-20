"""Semantic pipeline: links MvT/NvT publications to instrument articles via LICHT_TOE edges.

Scans publications with soort containing 'toelichting' for the structured
'Artikelsgewijze toelichting' section, then matches article numbers to article
nodes in the related instruments.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    RELATION_LICHT_TOE,
    RELATION_RAAKT,
    RELATION_RESULTED_IN,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, collection_from_id

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "mvt-article-linker"

_HEADING_PATTERN = re.compile(r"artikelsgewijze\s+toelichting", re.IGNORECASE)
_ARTICLE_PATTERN = re.compile(r"\bArtikel(?:en)?\s+(\d+[a-z]*)\b", re.IGNORECASE)

_MAX_HITS_PER_PUB = 200


class MvtArticleSemanticPipeline(SemanticPipelineBase):
    """Pipeline linking MvT publications to instrument articles via LICHT_TOE edges."""

    def run(self, *, since: Any = None) -> PipelineResult:
        result = PipelineResult()

        # Build optional since filter for the publications query
        since_filter = ""
        bind_vars: dict[str, Any] = {"s1_rels": [RELATION_RESULTED_IN, RELATION_RAAKT]}
        if since is not None:
            from lawgraph.core.time import iso_timestamp

            since_iso = iso_timestamp(since)
            if since_iso:
                since_filter = """
  LET recent_ids = (
    FOR r IN raw_sources
      FILTER r.source == 'tk' AND r.fetched_at >= @since
      FILTER r.external_id != null
      RETURN r.external_id
  )
  FILTER pub.props.external_id IN recent_ids"""
                bind_vars["since"] = since_iso

        aql = f"""
FOR pub IN publications
  FILTER CONTAINS(LOWER(pub.props.soort ?? ''), 'toelichting')
  FILTER pub.props.text != null AND LENGTH(pub.props.text) > 200
  {since_filter}
  LET dossier_ids = (
    FOR e IN edges
      FILTER e._from == pub._id AND e.relation == 'DEEL_VAN_DOSSIER'
      RETURN e._to
  )
  // Strategy 1: RESULTED_IN/RAAKT from dossier → instrument (enacted or linked laws)
  LET s1 = (
    FOR did IN dossier_ids
      FOR e2 IN edges
        FILTER e2._from == did AND e2.relation IN @s1_rels
        LET inst = DOCUMENT(e2._to)
        FILTER inst != null AND (inst.props.bwb_id != null OR inst.props.celex != null)
        RETURN DISTINCT {{id: inst._id, bwb_id: inst.props.bwb_id, celex: inst.props.celex}}
  )
  // Strategy 2: follow WIJZIGT/INTRODUCEERT/TREKT_IN edges from sibling publications
  //             to find which instruments the dossier targets
  LET s2 = (
    FOR did IN dossier_ids
      FOR e2 IN edges
        FILTER e2._to == did AND e2.relation == 'DEEL_VAN_DOSSIER'
        FOR e3 IN edges
          FILTER e3._from == e2._from
              AND e3.relation IN ['WIJZIGT', 'INTRODUCEERT', 'TREKT_IN']
          LET art = DOCUMENT(e3._to)
          FILTER art != null AND art.props.bwb_id != null
          FOR inst IN instruments
            FILTER inst.props.bwb_id == art.props.bwb_id
            RETURN DISTINCT {{id: inst._id, bwb_id: inst.props.bwb_id, celex: inst.props.celex}}
  )
  LET found_instruments = LENGTH(s1) > 0 ? s1 : s2
  FILTER LENGTH(found_instruments) > 0
  RETURN {{
    pub_id: pub._id,
    pub_key: pub._key,
    text: pub.props.text,
    instruments: found_instruments
  }}
"""

        rows = list(self.store.query(aql, bind_vars=bind_vars if bind_vars else None))
        if not rows:
            logger.debug("No MvT publications found for LICHT_TOE linking.")
            return result

        logger.info("MvT article linker: processing %d publications.", len(rows))

        # Collect all distinct (bwb_id, celex) pairs so we can load article
        # maps once per instrument rather than once per (publication × instrument).
        distinct_pairs: set[tuple[str | None, str | None]] = set()
        for row in rows:
            for inst in row.get("instruments") or []:
                distinct_pairs.add((inst.get("bwb_id"), inst.get("celex")))

        article_map_cache: dict[tuple[str | None, str | None], dict[str, Node]] = {
            pair: self._load_article_map(bwb_id=pair[0], celex=pair[1])
            for pair in distinct_pairs
        }

        for row in rows:
            pub_id = row.get("pub_id")
            pub_key = row.get("pub_key")
            text = row.get("text") or ""
            instruments = row.get("instruments") or []

            if not pub_id or not text:
                result.skipped += 1
                continue

            pub_node = Node(
                collection="publications",
                type=NodeType.PUBLICATION,
                key=pub_key,
                props={},
            )

            for inst in instruments:
                bwb_id = inst.get("bwb_id")
                celex = inst.get("celex")
                article_map = article_map_cache.get((bwb_id, celex))
                if not article_map:
                    continue

                hits = self._extract_licht_toe_hits(text, article_map)
                for article_node, confidence in hits:
                    created = self._create_semantic_edge(
                        from_node=pub_node,
                        to_node=article_node,
                        relation=RELATION_LICHT_TOE,
                        source=SEMANTIC_SOURCE,
                        confidence=confidence,
                        result=result,
                    )
                    if created:
                        result.created += 1
                    else:
                        result.updated += 1

        logger.info("MvT article semantic linker: %s.", result.summary())
        return result

    def _load_article_map(
        self, *, bwb_id: str | None, celex: str | None
    ) -> dict[str, Node]:
        """Return a mapping of article number → Node for the given instrument."""
        if not bwb_id and not celex:
            return {}

        bind_vars: dict[str, Any] = {"bwb_id": bwb_id, "celex": celex}
        aql = """
FOR art IN instrument_articles
  FILTER (art.props.bwb_id == @bwb_id) OR (art.props.celex == @celex)
  RETURN { number: art.props.article_number, id: art._id, key: art._key }
"""
        article_map: dict[str, Node] = {}
        try:
            rows = list(self.store.query(aql, bind_vars=bind_vars))
        except Exception as exc:
            logger.debug("Could not load article map for %s/%s: %s", bwb_id, celex, exc)
            return {}

        for row in rows:
            number = row.get("number")
            art_id: str = row.get("id") or ""
            art_key: str = row.get("key") or ""
            if not number or not art_id:
                continue
            num_str = str(number).strip().lower()
            collection = collection_from_id(art_id, COLLECTION_INSTRUMENT_ARTICLES)
            node = Node(
                collection=collection,
                type=NodeType.ARTICLE,
                key=art_key,
                props={"article_number": number, "bwb_id": bwb_id, "celex": celex},
            )
            if num_str not in article_map:
                article_map[num_str] = node

        return article_map

    def _extract_licht_toe_hits(
        self, text: str, article_map: dict[str, Node]
    ) -> list[tuple[Node, float]]:
        """Extract LICHT_TOE hits from the text.

        Returns a list of (Node, confidence) pairs, deduplicated by article node.
        """
        # Find the 'Artikelsgewijze toelichting' heading, if present.
        heading_match = _HEADING_PATTERN.search(text)
        heading_pos = heading_match.start() if heading_match else len(text)

        seen_keys: set[str] = set()
        hits: list[tuple[Node, float]] = []

        for m in _ARTICLE_PATTERN.finditer(text):
            if len(hits) >= _MAX_HITS_PER_PUB:
                break

            art_num = m.group(1).strip().lower()
            confidence = 0.90 if m.start() >= heading_pos else 0.55

            node = article_map.get(art_num)
            if node is None:
                # Try stripping leading zeros
                node = article_map.get(art_num.lstrip("0"))

            if node is None:
                continue

            node_key = node.key or art_num
            if node_key in seen_keys:
                continue
            seen_keys.add(node_key)
            hits.append((node, confidence))

        return hits
