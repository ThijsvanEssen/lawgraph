"""Semantic pipeline: REFERS_TO between the articles of a law of the Staatsblad the BWB does
not hold (yet).

Its XML has no links (``intref``) as a toestand of the BWB has: a reference is read from the
text of an article (``core/staatsblad_laws.own_references``): "artikel 2.8.16", "de artikelen
1.1.1 en 1.1.2", "artikel 3.1.1, eerste lid, van deze wet", not one followed by another law.
It points at the article of that number of the same law, when the law has it. Derived in full
on every run: an edge of the step from an article read that no reference supports goes.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_ARTICLES, RELATION_REFERS_TO
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key, node_id
from lawgraph.core.staatsblad_laws import own_references
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import staatsblad_laws as law_queries
from lawgraph.sources.addresses import edge_source

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
# Read from the words of the text, not from a link: "artikel 2.8.16" without a law after it
# is one of the law itself.
CONFIDENCE = 0.9


class StaatsbladLawReferencesSemanticPipeline(SemanticPipelineBase):
    """References between the articles of a law of the Staatsblad."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = list(law_queries.law_articles(self.store))
        keys = {row["key"] for row in rows}
        read: list[str] = []
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for row in self._track(rows, "articles", total=len(rows)):
            read.append(row["id"])
            for reference in own_references(row["text"] or ""):
                key = make_node_key(row["official_id"], reference.number)
                if key == row["key"] or key not in keys:
                    continue
                edges.add(
                    row["id"],
                    node_id(COLLECTION_ARTICLES, key),
                    RELATION_REFERS_TO,
                    source=EDGE_SOURCE,
                    confidence=CONFIDENCE,
                    meta=reference.meta(),
                )
        edges.flush_into(result)
        removed = edges.remove_stale(RELATION_REFERS_TO, EDGE_SOURCE, read)
        logger.info(
            "%d articles of laws of the Staatsblad read; %d references they no longer "
            "make removed.",
            len(read),
            removed,
        )
        self.add_outcomes(result)
        return result
