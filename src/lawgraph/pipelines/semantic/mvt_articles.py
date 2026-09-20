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

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "mvt-article-linker"

_CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)

_SINCE_FILTER = "FILTER doc.props.fetched_at >= @since"


def _targets_aql(since_filter: str) -> str:
    """One pass: per explanatory document, the nodes it explains.

    Those are the article versions (or articles, or the instrument itself) that
    the instrument legislated in the document's dossier introduced or changed.
    """
    return f"""
FOR doc IN {COLLECTION_DOCUMENTS}
  FILTER CONTAINS(LOWER(doc.props.kind ?? ''), 'toelichting')
  {since_filter}
  LET dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  LET instruments = (
    FOR dossier IN dossiers
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @legislated_in
        FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
        RETURN DISTINCT e._from
  )
  FILTER LENGTH(instruments) > 0
  LET changed = (
    FOR instrument IN instruments
      FOR e IN {COLLECTION_EDGES}
        FILTER e._from == instrument AND e.relation IN @change_relations
        FILTER STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
        RETURN DISTINCT e.meta.article_version == null
          ? e._to
          : CONCAT('{COLLECTION_ARTICLE_VERSIONS}/', e.meta.article_version)
  )
  RETURN {{
    document: doc._id,
    targets: LENGTH(changed) > 0 ? changed : instruments
  }}
"""


class MvtArticlesSemanticPipeline(SemanticPipelineBase):
    """Link explanatory memoranda to the article versions they explain."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        bind_vars: dict[str, Any] = {
            "part_of": RELATION_PART_OF,
            "legislated_in": RELATION_LEGISLATED_IN,
            "change_relations": list(_CHANGE_RELATIONS),
        }
        since_filter = ""
        if since is not None:
            since_filter = _SINCE_FILTER
            bind_vars["since"] = iso_timestamp(since)

        edges = EdgeWriter(self.store)
        documents = 0
        for row in self.store.query(_targets_aql(since_filter), bind_vars):
            document = row.get("document")
            targets = row.get("targets") or []
            if not document or not targets:
                result.skipped += 1
                continue
            documents += 1
            for target in targets:
                edges.add(
                    document,
                    target,
                    RELATION_EXPLAINS,
                    source=SEMANTIC_SOURCE,
                    confidence=1.0,
                )
        edges.flush()

        result.created += edges.created
        result.updated += edges.updated
        logger.info(
            "Explanatory memorandum linker: %d documents, %s.",
            documents,
            result.summary(),
        )
        return result
