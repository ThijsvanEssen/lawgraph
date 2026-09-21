"""Semantic pipeline: BWB regulation → BASED_ON → the article it is issued under.

The BWB XML states the legal basis in the preamble: the paragraph that starts with
"Gelet op" contains ``<extref bwb-id=… doc="jci1.3:c:BWBR0001947&artikel=125">``
elements. ``normalize bwb`` reads them (``core.bwb_xml.parse_toestand``) and keeps them on
the regulation as ``props.basis``; this pipeline turns each entry that names an article into

    Instrument(regulation) --BASED_ON--> Article(basis regulation, article)

Entries without an article number have no target and are skipped, as are
targets that are not in the graph and references to the regulation itself.

Only the regulations that state a basis are read, in chunks: per chunk one existence
check for the target articles.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_BASED_ON,
    SOURCE_BWB,
)
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-grondslagen-linker"

_CHUNK = 500

_BASIS_AQL = f"""
FOR regulation IN {COLLECTION_INSTRUMENTS}
  FILTER regulation.props.source == @source
  FILTER LENGTH(regulation.props.basis) > 0
  RETURN {{
    key: regulation._key,
    bwb_id: regulation.props.bwb_id,
    basis: regulation.props.basis
  }}
"""

# (regulation key, target article key, the "Gelet op" reference)
_Link = tuple[str, str, dict[str, Any]]


class BWBGrondslagenSemanticPipeline(SemanticPipelineBase):
    """Create BASED_ON edges from BWB regulations to their legal-basis articles."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None)
        rows = self.store.query(_BASIS_AQL, {"source": SOURCE_BWB})
        for chunk in chunked(self._track(rows, "regulations with a basis"), _CHUNK):
            self._link_chunk(chunk, edges, result)
        edges.flush_into(result)
        logger.info("BWB grondslagen: %s.", result.summary())
        return result

    def _link_chunk(
        self, rows: list[dict[str, Any]], edges: EdgeWriter, result: PipelineResult
    ) -> None:
        links: list[_Link] = []
        for row in rows:
            found = self._basis_links(row)
            if not found:
                result.skipped += 1
            links.extend(found)
        if not links:
            return

        targets = self.store.existing_keys(
            COLLECTION_ARTICLES, {target for _, target, _ in links}
        )
        for source, target, ref in links:
            if target not in targets:
                result.skipped += 1
                continue
            edges.add(
                f"{COLLECTION_INSTRUMENTS}/{source}",
                f"{COLLECTION_ARTICLES}/{target}",
                RELATION_BASED_ON,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"text": ref["text"], "doc": ref["doc"]},
            )

    @staticmethod
    def _basis_links(row: dict[str, Any]) -> list[_Link]:
        """Candidate edges of one regulation: basis entries that name an article."""
        bwb_id = str(row.get("bwb_id") or "").upper()
        links: list[_Link] = []
        for ref in row.get("basis") or []:
            basis_id = str(ref.get("bwb_id") or "").upper()
            if not ref.get("article") or not basis_id or basis_id == bwb_id:
                continue  # no target article, or a reference to itself
            links.append((row["key"], make_node_key(basis_id, ref["article"]), ref))
        return links
