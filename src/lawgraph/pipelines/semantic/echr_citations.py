"""Semantic pipeline: ECHR judgments → CITES_ARTICLE (ECHR Convention articles).

ECHR HUDOC stores the cited Convention articles in the ``articles`` field of
each judgment record (e.g. ["6", "8", "13"]).  We map those article numbers
to instrument_articles for an "ECHR Convention" instrument in the graph.

If the ECHR Convention instrument does not yet exist as a stub it is created
automatically so subsequent pipeline runs can enrich it.

We also link judgments to any NL/EU instruments mentioned in the judgment
``conclusion`` text via BWBR/CELEX pattern matching.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_CITES_ARTICLE,
    RELATION_MENTIONS_INSTRUMENT,
    SOURCE_ECHR,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "echr-citation-linker"

_ECHR_CONVENTION_BWB_STUB = "ECHR-CONVENTION"
_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)


def _ensure_echr_convention_instrument(store: Any) -> Node:
    """Get or create a stub instrument node for the ECHR Convention."""
    key = make_node_key(_ECHR_CONVENTION_BWB_STUB)
    existing = store.get_node(COLLECTION_INSTRUMENTS, key)
    if existing is not None:
        return existing
    node = Node(
        collection=COLLECTION_INSTRUMENTS,
        type=NodeType.INSTRUMENT,
        key=key,
        labels=["ECHR", "Convention"],
        props={
            "bwb_id": _ECHR_CONVENTION_BWB_STUB,
            "title": "Europees Verdrag voor de Rechten van de Mens (EVRM)",
            "citation_title": "EVRM",
            "jurisdiction": "eu",
            "display_name": "EVRM",
            "stub": False,
        },
    )
    return store.insert_or_update(node)


def _ensure_echr_article(
    store: Any, convention: Node, article_label: str
) -> Node | None:
    """Get or create a stub article node for an ECHR Convention article."""
    if not article_label:
        return None
    key = make_node_key(_ECHR_CONVENTION_BWB_STUB, article_label)
    node = Node(
        collection=COLLECTION_INSTRUMENT_ARTICLES,
        type=NodeType.ARTICLE,
        key=key,
        labels=["ECHR"],
        props={
            "bwb_id": _ECHR_CONVENTION_BWB_STUB,
            "label": article_label,
            "article_number": article_label,
            "title": f"Artikel {article_label} EVRM",
            "display_name": f"Artikel {article_label} EVRM",
            "instrument_id": convention.arango_id,
        },
    )
    return store.insert_or_update(node)


class EchrCitationsPipeline(SemanticPipelineBase):
    """Links ECHR judgments to cited Convention articles and mentioned instruments."""

    def _link_convention_articles(
        self,
        result: PipelineResult,
        judgments: list[dict],
        convention: Node,
        article_cache: dict[str, Node | None],
        edge_batch: list[dict],
    ) -> list[dict]:
        """Append CITES_ARTICLE edges for every judgment → Convention article pair.

        Returns the (possibly grown) edge_batch so the caller can flush it.
        """
        for row in judgments:
            j_id = row.get("j_id")
            j_key = row.get("j_key")
            if not j_id:
                result.skipped += 1
                continue

            judgment_node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=j_key,
                props={},
            )

            articles = row.get("articles") or []
            if isinstance(articles, str):
                articles = [articles]

            for art_label in articles:
                label = str(art_label).strip()
                if not label:
                    continue

                if label not in article_cache:
                    try:
                        article_cache[label] = _ensure_echr_article(
                            self.store, convention, label
                        )
                    except Exception as exc:
                        logger.debug(
                            "ECHR: could not ensure article %s: %s", label, exc
                        )
                        article_cache[label] = None

                art_node = article_cache[label]
                if art_node is None:
                    continue

                edge_doc = self._make_edge_doc(
                    from_node=judgment_node,
                    to_node=art_node,
                    relation=RELATION_CITES_ARTICLE,
                    source=SEMANTIC_SOURCE,
                    confidence=0.95,
                    meta={"article": label, "instrument": "EVRM"},
                )
                if edge_doc:
                    edge_batch.append(edge_doc)
                    if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                        created, updated = self._flush_edge_batch(edge_batch, result)
                        result.created += created
                        result.updated += updated
                        edge_batch = []

        return edge_batch

    def _link_bwb_mentions(
        self,
        result: PipelineResult,
        judgments: list[dict],
        bwb_instruments: dict[str, Node],
        edge_batch: list[dict],
    ) -> list[dict]:
        """Append MENTIONS_INSTRUMENT edges for BWB IDs found in judgment conclusions.

        Returns the (possibly grown) edge_batch so the caller can flush it.
        """
        for row in judgments:
            j_id = row.get("j_id")
            j_key = row.get("j_key")
            if not j_id:
                continue

            conclusion = row.get("conclusion") or ""
            if not conclusion:
                continue

            judgment_node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=j_key,
                props={},
            )

            bwb_ids = {m.group(1).upper() for m in _BWBR_PATTERN.finditer(conclusion)}
            for bwb_id in bwb_ids:
                inst_node = bwb_instruments.get(bwb_id)
                if inst_node is None:
                    continue
                edge_doc = self._make_edge_doc(
                    from_node=judgment_node,
                    to_node=inst_node,
                    relation=RELATION_MENTIONS_INSTRUMENT,
                    source=SEMANTIC_SOURCE,
                    confidence=0.80,
                    meta={"match_type": "bwb_text_scan"},
                )
                if edge_doc:
                    edge_batch.append(edge_doc)
                    if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                        created, updated = self._flush_edge_batch(edge_batch, result)
                        result.created += created
                        result.updated += updated
                        edge_batch = []

        return edge_batch

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()

        # Fetch all ECHR judgment nodes
        aql = f"""
FOR j IN {COLLECTION_JUDGMENTS}
  FILTER j.props.source == @source
  FILTER j.props.articles != null OR j.props.conclusion != null
  RETURN {{
    j_id: j._id,
    j_key: j._key,
    articles: j.props.articles,
    conclusion: j.props.conclusion
  }}
"""
        try:
            rows = list(self.store.query(aql, {"source": SOURCE_ECHR}))
        except Exception as exc:
            logger.warning("ECHR citations: query failed: %s", exc)
            return result

        if not rows:
            logger.debug("ECHR citations: no ECHR judgments found.")
            return result

        logger.info("ECHR citations: processing %d judgments.", len(rows))

        # Ensure the ECHR Convention instrument exists
        try:
            convention = _ensure_echr_convention_instrument(self.store)
        except Exception as exc:
            logger.warning(
                "ECHR citations: could not ensure Convention instrument: %s", exc
            )
            return result

        # Collect all BWB IDs mentioned across all judgments so we can look
        # them up in one query instead of one per (judgment × bwb_id).
        all_bwb_ids: set[str] = set()
        for row in rows:
            conclusion = row.get("conclusion") or ""
            for m in _BWBR_PATTERN.finditer(conclusion):
                all_bwb_ids.add(m.group(1).upper())

        bwb_id_to_node: dict[str, Node] = {}
        if all_bwb_ids:
            batch_aql = """
FOR inst IN instruments
  FILTER UPPER(inst.props.bwb_id) IN @bwb_ids
  RETURN inst
"""
            try:
                inst_rows = list(
                    self.store.query(batch_aql, {"bwb_ids": list(all_bwb_ids)})
                )
                for inst_doc in inst_rows:
                    key = inst_doc.get("props", {}).get("bwb_id", "").upper()
                    if key:
                        bwb_id_to_node[key] = Node(
                            collection=COLLECTION_INSTRUMENTS,
                            type=NodeType.INSTRUMENT,
                            key=inst_doc["_key"],
                            props={},
                        )
            except Exception as exc:
                logger.warning("ECHR citations: batch BWB lookup failed: %s", exc)

        article_cache: dict[str, Node | None] = {}
        edge_batch: list[dict] = []

        edge_batch = self._link_convention_articles(
            result, rows, convention, article_cache, edge_batch
        )
        edge_batch = self._link_bwb_mentions(result, rows, bwb_id_to_node, edge_batch)

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info("ECHR citations: %s.", result.summary())
        return result
