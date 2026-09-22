"""Semantic pipeline: ECHR judgments → REFERS_TO → Convention articles.

ECHR HUDOC stores the cited Convention articles in the ``articles`` field of
each judgment record (e.g. ["6", "8", "13"]). Those article numbers are mapped
to the articles of an "ECHR Convention" instrument in the graph.

If the ECHR Convention instrument does not yet exist as a stub it is created
automatically so subsequent pipeline runs can enrich it.

Judgments are also linked to any NL/EU instruments named in the judgment
``conclusion`` text via BWBR/CELEX pattern matching.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    ECHR_CONVENTION_ID,
    RELATION_REFERS_TO,
    SOURCE_ECHR,
)
from lawgraph.core.identifiers import BWB_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "echr-citation-linker"


def _ensure_echr_convention_instrument(store: Any) -> Node:
    """Get or create a stub instrument node for the ECHR Convention."""
    key = make_node_key(ECHR_CONVENTION_ID)
    existing = store.get_node(COLLECTION_INSTRUMENTS, key)
    if existing is not None:
        return existing
    node = Node(
        collection=COLLECTION_INSTRUMENTS,
        type=NodeType.INSTRUMENT,
        key=key,
        labels=["ECHR", "Convention"],
        props={
            "bwb_id": ECHR_CONVENTION_ID,
            "title": "Europees Verdrag voor de Rechten van de Mens (EVRM)",
            "citation_title": "EVRM",
            "jurisdiction": "eu",
            "kind": "verdrag",
            "display_name": "EVRM",
            "stub": False,
        },
    )
    stored, _ = store.insert_or_update(node)
    return stored


def _ensure_echr_article(
    store: Any, convention: Node, article_label: str
) -> Node | None:
    """Get or create a stub article node for an ECHR Convention article."""
    if not article_label:
        return None
    key = make_node_key(ECHR_CONVENTION_ID, article_label)
    node = Node(
        collection=COLLECTION_ARTICLES,
        type=NodeType.ARTICLE,
        key=key,
        labels=["ECHR"],
        props={
            "bwb_id": ECHR_CONVENTION_ID,
            "label": article_label,
            "article_number": article_label,
            "title": f"Artikel {article_label} EVRM",
            "display_name": f"Artikel {article_label} EVRM",
            "instrument_id": convention.arango_id,
        },
    )
    stored, _ = store.insert_or_update(node)
    return stored


class ECHRSemanticPipeline(SemanticPipelineBase):
    """Links ECHR judgments to cited Convention articles and mentioned instruments."""

    def _link_convention_articles(
        self,
        result: PipelineResult,
        judgments: list[dict],
        convention: Node,
        article_cache: dict[str, Node | None],
        edges: EdgeWriter,
    ) -> None:
        """REFERS_TO edges for every judgment → Convention article pair."""
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
                    article_cache[label] = _ensure_echr_article(
                        self.store, convention, label
                    )

                art_node = article_cache[label]
                if art_node is None:
                    continue

                edge_doc = self._make_edge_doc(
                    from_node=judgment_node,
                    to_node=art_node,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=0.95,
                    meta={"article": label, "instrument": "EVRM"},
                )
                if edge_doc:
                    edges.add_doc(edge_doc)

    def _link_bwb_mentions(
        self,
        result: PipelineResult,
        judgments: list[dict],
        bwb_instruments: dict[str, Node],
        edges: EdgeWriter,
    ) -> None:
        """REFERS_TO edges for BWB IDs found in judgment conclusions."""
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

            bwb_ids = {m.group(1).upper() for m in BWB_ID_PATTERN.finditer(conclusion)}
            for bwb_id in bwb_ids:
                inst_node = bwb_instruments.get(bwb_id)
                if inst_node is None:
                    continue
                edge_doc = self._make_edge_doc(
                    from_node=judgment_node,
                    to_node=inst_node,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=0.80,
                    meta={"match_type": "bwb_text_scan"},
                )
                if edge_doc:
                    edges.add_doc(edge_doc)

    def run(self) -> PipelineResult:
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
        judgments = self.store.query(aql, {"source": SOURCE_ECHR})
        rows = list(self._track(judgments, "ECHR judgments"))

        if not rows:
            logger.debug("ECHR citations: no ECHR judgments found.")
            return result

        logger.info("ECHR citations: processing %d judgments.", len(rows))

        # Ensure the ECHR Convention instrument exists
        convention = _ensure_echr_convention_instrument(self.store)

        # Collect all BWB IDs mentioned across all judgments so we can look
        # them up in one query instead of one per (judgment × bwb_id).
        all_bwb_ids: set[str] = set()
        for row in rows:
            conclusion = row.get("conclusion") or ""
            for m in BWB_ID_PATTERN.finditer(conclusion):
                all_bwb_ids.add(m.group(1).upper())

        bwb_id_to_node: dict[str, Node] = {}
        if all_bwb_ids:
            batch_aql = f"""
FOR inst IN {COLLECTION_INSTRUMENTS}
  FILTER inst.props.bwb_id IN @bwb_ids
  RETURN {{_key: inst._key, props: {{bwb_id: inst.props.bwb_id}}}}
"""
            bind = {"bwb_ids": list(all_bwb_ids)}
            for inst_doc in self.store.query(batch_aql, bind):
                key = inst_doc.get("props", {}).get("bwb_id", "").upper()
                if key:
                    bwb_id_to_node[key] = Node(
                        collection=COLLECTION_INSTRUMENTS,
                        type=NodeType.INSTRUMENT,
                        key=inst_doc["_key"],
                        props={},
                    )

        article_cache: dict[str, Node | None] = {}
        edges = EdgeWriter(self.store, what=None)

        self._link_convention_articles(result, rows, convention, article_cache, edges)
        self._link_bwb_mentions(result, rows, bwb_id_to_node, edges)
        edges.flush_into(result)

        return result
