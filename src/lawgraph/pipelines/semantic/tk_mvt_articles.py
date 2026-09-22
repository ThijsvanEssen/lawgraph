"""Semantic pipeline: the sections of explanatory memoranda → EXPLAINS → the article each explains.

``semantic tk-mvt`` links a memorandum to everything its dossier changed. The artikelsgewijs
part of the memorandum says more: a heading and a toelichting per article (``props.sections``,
written by ``normalize tk-content``). ``core/mvt_articles.py`` reads which article of which
law a section is about; this pipeline matches that with what the dossier changed::

    Document --PART_OF--> Dossier <--LEGISLATED_IN-- Instrument
    Instrument --AMENDS/INTRODUCES/REPEALS--> Article

and writes ``EXPLAINS`` to the ArticleVersion the change created (the Article when it names
none), with the section in ``meta``.

An edge is one per (document, article), so an article that several sections explain has one
edge that lists them all: ``meta.section_anchor`` and the fields beside it describe the surest
of them, ``meta.sections`` every one. The edge is the one ``semantic tk-mvt`` writes for the
whole dossier, upgraded in place (same key): this pipeline's source and confidence are what the
edge carries when it exists, whichever of the two ran first, because ``tk-mvt`` leaves an edge
alone that this pipeline has written.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_INTRODUCES,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
)
from lawgraph.core.kamerstuk_xml import QUALITY_EXPLICIT, QUALITY_IMPLICIT
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.mvt_articles import (
    Change,
    Law,
    Reference,
    explained_targets,
    find_references,
    is_introduction,
)
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase
from .tk_mvt import SEMANTIC_SOURCE_SECTIONS

logger = get_logger(__name__)

SEMANTIC_SOURCE = SEMANTIC_SOURCE_SECTIONS

_CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)

# Rows carry the text of a paper: fewer per cursor batch than the default 1000.
_BATCH_SIZE = 20

# One pass: per memorandum with sections, what its dossier legislated and changed.
#
# A budget paper explains policy articles and a paper without article headings has no sections
# to read; a dossier that legislated nothing has nothing to link to.
_PAPERS_AQL = f"""
FOR doc IN {COLLECTION_DOCUMENTS}
  FILTER CONTAINS(LOWER(doc.props.kind || ''), 'toelichting')
  FILTER doc.props.budget != true
  FILTER doc.props.structure_quality IN @qualities
  FILTER doc.props.text != null
  LET paper_dossiers = (
    FOR e IN {COLLECTION_EDGES}
      FILTER e._from == doc._id AND e.relation == @part_of
      FILTER STARTS_WITH(e._to, '{COLLECTION_DOSSIERS}/')
      RETURN e._to
  )
  LET legislated = (
    FOR dossier IN paper_dossiers
      FOR e IN {COLLECTION_EDGES}
        FILTER e._to == dossier AND e.relation == @legislated_in
        FILTER STARTS_WITH(e._from, '{COLLECTION_INSTRUMENTS}/')
        RETURN DISTINCT e._from
  )
  FILTER LENGTH(legislated) > 0
  LET own = (
    FOR instrument IN legislated
      LET bwb_id = DOCUMENT(instrument).props.bwb_id
      FILTER bwb_id != null
      RETURN bwb_id
  )
  LET changes = (
    FOR instrument IN legislated
      FOR e IN {COLLECTION_EDGES}
        FILTER e._from == instrument AND e.relation IN @change_relations
        FILTER STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
        LET article = DOCUMENT(e._to)
        FILTER article.props.bwb_id != null AND article.props.article_number != null
        RETURN DISTINCT {{
          bwb_id: article.props.bwb_id,
          number: article.props.article_number,
          article: e._to,
          version: e.meta.article_version,
          relation: e.relation
        }}
  )
  LET wanted = UNIQUE(APPEND(own, changes[*].bwb_id))
  LET laws = (
    FOR law IN {COLLECTION_INSTRUMENTS}
      FILTER law.props.bwb_id != null AND law.props.bwb_id IN wanted
      RETURN {{
        bwb_id: law.props.bwb_id,
        names: [law.props.title, law.props.citation_title],
        codes: [law.props.short_title]
      }}
  )
  RETURN {{
    document: doc._id,
    text: doc.props.text,
    sections: doc.props.sections,
    own: own,
    changes: changes,
    laws: laws
  }}
"""


def _laws(rows: list[dict[str, Any]], own_bwb_id: str | None) -> list[Law]:
    """The laws the dossier changes (the law the bill makes is not one of them)."""
    return [
        Law(
            bwb_id=str(row["bwb_id"]),
            names=tuple(str(n) for n in row.get("names") or [] if n),
            codes=tuple(str(c) for c in row.get("codes") or [] if c),
        )
        for row in rows
        if row.get("bwb_id") and row["bwb_id"] != own_bwb_id
    ]


def _changes(rows: list[dict[str, Any]]) -> list[Change]:
    return [
        Change(
            bwb_id=str(row["bwb_id"]),
            number=str(row["number"]),
            article=str(row["article"]),
            version=row.get("version"),
            relation=str(row["relation"]),
        )
        for row in rows
    ]


def edge_meta(references: list[Reference]) -> dict[str, Any]:
    """The ``meta`` of the edge to one article: the surest section, and every section.

    Sections are one per id (the surest way a section names the article counts), in the order
    of the document.
    """
    by_section: dict[str, Reference] = {}
    for reference in references:
        known = by_section.get(reference.section_id)
        if known is None or reference.confidence > known.confidence:
            by_section[reference.section_id] = reference
    listed = sorted(by_section.values(), key=lambda r: r.char_start)
    best = min(listed, key=lambda r: (-r.confidence, r.char_start))
    return {
        "section_anchor": best.section_id,
        "char_start": best.char_start,
        "char_end": best.char_end,
        "match_type": best.match_type,
        "heading": best.heading,
        "sections": [
            {
                "section_anchor": r.section_id,
                "heading": r.heading,
                "char_start": r.char_start,
                "char_end": r.char_end,
                "match_type": r.match_type,
                "confidence": r.confidence,
            }
            for r in listed
        ],
    }


class TKMvtArticlesSemanticPipeline(SemanticPipelineBase):
    """EXPLAINS from the sections of a memorandum to the articles they are about."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        bind_vars: dict[str, Any] = {
            "qualities": [QUALITY_EXPLICIT, QUALITY_IMPLICIT],
            "part_of": RELATION_PART_OF,
            "legislated_in": RELATION_LEGISLATED_IN,
            "change_relations": list(_CHANGE_RELATIONS),
        }
        edges = EdgeWriter(self.store, what=None)
        papers = self.store.query(_PAPERS_AQL, bind_vars, batch_size=_BATCH_SIZE)
        for row in self._track(papers, "explanatory memoranda"):
            try:
                written = self._explain(row, edges)
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Memorandum %s skipped: %s", row.get("document"), exc)
                result.skipped += 1
                continue
            if not written:
                result.skipped += 1
        edges.flush_into(result)
        return result

    def _explain(self, row: dict[str, Any], edges: EdgeWriter) -> int:
        """Queue the edges of one memorandum; how many."""
        changes = _changes(row.get("changes") or [])
        own = row.get("own") or []
        own_bwb_id = (
            own[0] if len(own) == 1 and is_introduction(changes, own[0]) else None
        )
        references = find_references(
            row["text"],
            row.get("sections") or [],
            _laws(row.get("laws") or [], own_bwb_id),
            own_bwb_id=own_bwb_id,
        )
        explained = explained_targets(references, changes, self._article_exists)
        for target, refs in explained.items():
            meta = edge_meta(refs)
            edges.add(
                row["document"],
                target,
                RELATION_EXPLAINS,
                source=SEMANTIC_SOURCE,
                confidence=max(r.confidence for r in refs),
                meta=meta,
            )
        return len(explained)

    def _article_exists(self, article_id: str) -> bool:
        key = article_id.split("/", 1)[1]
        return self._lookup_node(COLLECTION_ARTICLES, key) is not None
