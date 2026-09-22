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

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    EXPLANATORY_KIND_MARKER,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "mvt-article-linker"
# The source of the edges ``semantic tk-mvt-articles`` writes, which this pipeline leaves alone.
SEMANTIC_SOURCE_SECTIONS = "mvt-section-linker"

# A dossier-level edge says that the memorandum explains the change of the dossier as a whole,
# not which of its articles a passage is about: every article the dossier changed is a
# candidate, not a finding. It claims no more than half.
DOSSIER_CONFIDENCE = 0.5

_CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)

# One pass: per explanatory document, the nodes it explains.
#
# Those are the article versions (or articles, or the instrument itself) that
# the instrument legislated in the document's dossier introduced or changed.
_TARGETS_AQL = f"""
FOR doc IN {COLLECTION_DOCUMENTS}
  FILTER CONTAINS(LOWER(doc.props.kind || ''), '{EXPLANATORY_KIND_MARKER}')
  LET dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  LET instruments = (
    FOR dossier IN {COLLECTION_DOSSIERS}
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @legislated_in
        FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
        RETURN DISTINCT e._from
  )
  FILTER LENGTH(instruments) > 0
  LET upgraded = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @explains AND e.source == @sections_source
      RETURN e._to
  )
  LET changed = (
    FOR instrument IN {COLLECTION_INSTRUMENTS}
      FOR e IN {COLLECTION_EDGES}
        FILTER e._from == instrument AND e.relation IN @change_relations
        FILTER STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
        RETURN DISTINCT e.meta.article_version == null
          ? e._to
          : CONCAT('{COLLECTION_ARTICLE_VERSIONS}/', e.meta.article_version)
  )
  RETURN {{
    document: doc._id,
    targets: MINUS(LENGTH(changed) > 0 ? changed : instruments, upgraded)
  }}
"""


class TKMvtSemanticPipeline(SemanticPipelineBase):
    """Link explanatory memoranda to the article versions they explain."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        bind_vars: dict[str, Any] = {
            "part_of": RELATION_PART_OF,
            "legislated_in": RELATION_LEGISLATED_IN,
            "explains": RELATION_EXPLAINS,
            "sections_source": SEMANTIC_SOURCE_SECTIONS,
            "change_relations": list(_CHANGE_RELATIONS),
        }

        edges = EdgeWriter(self.store, what=None)
        targets = self.store.query(_TARGETS_AQL, bind_vars)
        for row in self._track(targets, "explanatory memoranda"):
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
