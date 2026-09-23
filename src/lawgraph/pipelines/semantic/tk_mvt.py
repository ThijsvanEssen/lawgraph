"""Semantic pipeline: explanatory memoranda (MvT/NvT) → EXPLAINS → what they explain.

An explanatory memorandum belongs to a dossier, and the instrument that was
legislated in that dossier says which articles it introduced or changed. That
chain is recorded in the graph, so the link is read rather than guessed::

    Document --PART_OF--> Dossier <--LEGISLATED_IN-- Instrument
    Instrument --AMENDS/INTRODUCES/REPEALS--> Article

The edge targets the ArticleVersion the amendment created when the amendment
names one, the Article itself otherwise, and the Instrument when it changed no
articles at all.
"""

from __future__ import annotations

from lawgraph.config.constants import (
    RELATION_EXPLAINS,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "mvt-article-linker"
# The source of the edges ``semantic tk-mvt-articles`` writes, which this pipeline leaves alone.
SEMANTIC_SOURCE_SECTIONS = "mvt-section-linker"

# A dossier-level edge says that the memorandum explains the change of the dossier as a whole,
# not which of its articles a passage is about: every article the dossier changed is a
# candidate, not a finding. It claims no more than half.
DOSSIER_CONFIDENCE = 0.5


class TKMvtSemanticPipeline(SemanticPipelineBase):
    """Link explanatory memoranda to the article versions they explain."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None)
        memoranda = semantic_queries.memorandum_targets(
            self.store, sections_source=SEMANTIC_SOURCE_SECTIONS
        )
        for row in self._track(memoranda, "explanatory memoranda"):
            document = row.get("document")
            targets = row.get("targets") or []
            if not document or not targets:
                result.skipped += 1
                continue
            for target in targets:
                edges.add(
                    document,
                    target,
                    RELATION_EXPLAINS,
                    source=SEMANTIC_SOURCE,
                    confidence=DOSSIER_CONFIDENCE,
                )
        edges.flush_into(result)
        return result
