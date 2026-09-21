"""``semantic bwb-annexes``: an article that names an annex is scoped by it.

SCOPED_BY from an article to the annex its text refers to ("vermeld in bijlage I"), with the
detected scope type (fixed or discretionary). The annex nodes themselves, and their PART_OF
edge to the regulation, are made by ``normalize bwb`` from the toestand it parses; a
reference to an annex that is not there gets a stub, so the graph stays connected.
"""

from __future__ import annotations

from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    RELATION_SCOPED_BY,
    SOURCE_BWB,
)
from lawgraph.core.annex_xml import ANNEX_EDGE_SOURCE, annex_node_key
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.pipelines.semantic._annex_detect import detect_annex_references
from lawgraph.pipelines.semantic.base import SemanticPipelineBase, slim

logger = get_logger(__name__)

SEMANTIC_SOURCE = ANNEX_EDGE_SOURCE


class BWBAnnexesSemanticPipeline(SemanticPipelineBase):
    """Extract annex nodes from BWB XML and link referencing articles."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        self._link_articles(result, self._annex_keys())
        logger.info("Annex links: %s.", result.summary())
        return result

    def _annex_keys(self) -> set[str]:
        """The annexes ``normalize bwb`` made of the toestanden (and earlier stubs)."""
        return set(self.store.query(f"FOR a IN {COLLECTION_ANNEXES} RETURN a._key"))

    def _link_articles(self, result: PipelineResult, known_keys: set[str]) -> None:
        edges = EdgeWriter(self.store, what=None)
        articles = self._load_articles_mentioning_annex()
        for doc in self._track(articles, "articles"):
            article = Node.from_document(COLLECTION_ARTICLES, doc)
            text = article.props.get("text") or ""
            bwb_id = str(article.props.get("bwb_id") or "")
            if not text or not bwb_id:
                result.skipped += 1
                continue
            for hit in detect_annex_references(text):
                annex = self._ensure_annex(bwb_id, hit.label, known_keys)
                if annex is None:
                    continue
                edge = self._make_edge_doc(
                    from_node=article,
                    to_node=annex,
                    relation=RELATION_SCOPED_BY,
                    source=SEMANTIC_SOURCE,
                    confidence=0.9 if hit.label else 0.7,
                    meta={
                        "start": hit.start,
                        "end": hit.end,
                        "text": hit.text,
                        "scope_type": hit.scope_type,
                    },
                )
                if edge:
                    edges.add_doc(edge)
        edges.flush_into(result)

    def _load_articles_mentioning_annex(self) -> Iterable[dict[str, Any]]:
        aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.text != null
            FILTER CONTAINS(LOWER(doc.props.text), 'bijlage')
            RETURN {slim("doc", "bwb_id", "text")}
        """
        return self.store.query(aql)

    def _ensure_annex(
        self, bwb_id: str, label: str | None, known_keys: set[str]
    ) -> Node | None:
        """Return the annex node for (bwb_id, label), creating a stub if needed."""
        key = annex_node_key(bwb_id, label)
        if key in known_keys:
            return Node(
                collection=COLLECTION_ANNEXES,
                type=NodeType.ANNEX,
                key=key,
                props={},
                _skip_validation=True,
            )
        node = self.store.ensure_stub_node(
            COLLECTION_ANNEXES,
            key,
            NodeType.ANNEX,
            {
                "bwb_id": bwb_id,
                "label": label,
                "display_name": f"Annex {label}".strip() if label else "Annex",
                "source": SOURCE_BWB,
            },
        )
        if node is not None:
            known_keys.add(key)
        return node
