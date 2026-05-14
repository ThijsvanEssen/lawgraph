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

import re
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_CITES_ARTICLE,
    RELATION_MENTIONS_INSTRUMENT,
    SOURCE_ECHR,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, PipelineResult, make_node_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "echr-citation-linker"

_ECHR_CONVENTION_BWB_STUB = "ECHR-CONVENTION"
_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)
_CELEX_PATTERN = re.compile(r"\b(\d[A-Z]{1,2}\d{4}[A-Z]?\d{4,6}(?:[A-Z]\d*)?)\b")


def _ensure_echr_convention_instrument(store: Any) -> Node:
    """Get or create a stub instrument node for the ECHR Convention."""
    key = make_node_key(_ECHR_CONVENTION_BWB_STUB)
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
            "instrument_id": convention.id,
        },
    )
    return store.insert_or_update(node)


class EchrCitationsPipeline(SemanticPipelineBase):
    """Links ECHR judgments to cited Convention articles and mentioned instruments."""

    def run(self, *, since: Any = None) -> PipelineResult:
        result = PipelineResult()

        # Fetch all ECHR judgment nodes
        aql = """
FOR j IN judgments
  FILTER j.props.source == @source
  FILTER j.props.articles != null OR j.props.conclusion != null
  RETURN {
    j_id: j._id,
    j_key: j._key,
    articles: j.props.articles,
    conclusion: j.props.conclusion
  }
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

        # Cache article nodes by label to avoid repeated upserts
        article_cache: dict[str, Node | None] = {}

        for row in rows:
            j_id = row.get("j_id")
            j_key = row.get("j_key")
            if not j_id:
                result.skipped += 1
                continue

            judgment_node = Node(
                collection="judgments",
                type=NodeType.JUDGMENT,
                key=j_key,
                props={},
            )

            # ── Convention article citations ──────────────────────────────
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

                created = self._create_semantic_edge(
                    from_node=judgment_node,
                    to_node=art_node,
                    relation=RELATION_CITES_ARTICLE,
                    source=SEMANTIC_SOURCE,
                    confidence=0.95,
                    meta={"article": label, "instrument": "EVRM"},
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

            # ── NL/EU instrument mentions in conclusion ───────────────────
            conclusion = row.get("conclusion") or ""
            if not conclusion:
                continue

            bwb_ids = {m.group(1).upper() for m in _BWBR_PATTERN.finditer(conclusion)}
            for bwb_id in bwb_ids:
                inst_aql = """
FOR inst IN instruments
  FILTER UPPER(inst.props.bwb_id) == @bwb_id
  LIMIT 1
  RETURN inst
"""
                try:
                    inst_rows = list(self.store.query(inst_aql, {"bwb_id": bwb_id}))
                except Exception:
                    continue
                for inst_doc in inst_rows:
                    inst_node = Node(
                        collection=COLLECTION_INSTRUMENTS,
                        type=NodeType.INSTRUMENT,
                        key=inst_doc["_key"],
                        props={},
                    )
                    created = self._create_semantic_edge(
                        from_node=judgment_node,
                        to_node=inst_node,
                        relation=RELATION_MENTIONS_INSTRUMENT,
                        source=SEMANTIC_SOURCE,
                        confidence=0.80,
                        meta={"match_type": "bwb_text_scan"},
                        result=result,
                    )
                    if created:
                        result.created += 1
                    else:
                        result.updated += 1

        logger.info("ECHR citations: %s.", result.summary())
        return result
