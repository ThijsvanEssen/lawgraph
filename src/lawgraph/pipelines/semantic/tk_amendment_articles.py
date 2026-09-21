"""Semantic pipeline that detects legislative amendment language in TK documents.

A bill (Document) that says it changes an article gets an AMENDS / INTRODUCES /
REPEALS edge to that article with status ``voorgesteld``: the change is proposed,
not yet law. The instrument that eventually enacts it carries the canonical edge,
written by ``bwb_amendments`` from the BWB metadata.
"""

from __future__ import annotations

import re
from typing import Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
)
from lawgraph.core.citations import CitationHit, make_snippet, strip_xml
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter
from lawgraph.pipelines.semantic.base import SemanticPipelineBase, slim

logger = get_logger(__name__)

SEMANTIC_SOURCE = "amendment-article-linker"

# ---------------------------------------------------------------------------
# Regex patterns for Dutch legislative amendment boilerplate
# ---------------------------------------------------------------------------

# Optional comma-separated lid/onderdeel modifiers between an article number
# and the verb that signals the amendment kind. Matches the Dutch
# wetstechniek conventions used in voorstellen-van-wet:
#   "Artikel 36f, eerste lid, komt te luiden:"
#   "Artikel 36i, eerste lid, onder d, vervalt."
#   "Artikel 5, tweede lid, wordt als volgt gewijzigd:"
# The non-greedy ``{0,3}`` cap on repeats prevents runaway scans without
# losing realistic depth (lid + onderdeel + sub-onderdeel).
_LID_ONDERDEEL = r"(?:\s*,\s+[^,.\n]{1,60}){0,3}\s*,?"

# "Artikel 5 wordt als volgt gewijzigd:" / "Artikel 5, eerste lid, wordt gewijzigd"
_WORDT_GEWIJZIGD = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)"
    + _LID_ONDERDEEL
    + r"\s+(?:van\s+(?:de\s+)?(?:wet|het\s+wetboek|het\s+besluit)"
    + r"\s+[^,\n]{0,60}\s+)?wordt\s+(?:als\s+volgt\s+)?gewijzigd",
    re.IGNORECASE,
)

# "Na artikel 5 wordt een artikel ingevoegd" / "een nieuw artikel 5a ingevoegd"
_WORDT_INGEVOEGD = re.compile(
    r"\b(?:Na|na|In)\s+artikel\s+(\d+[a-z]*)\s+wordt\s+een\s+(?:nieuw\s+)?artikel\s+(\d+[a-z]*)\s+ingevoegd",
    re.IGNORECASE,
)

# "Artikel 5 vervalt" / "Artikel 5, eerste lid, onder d, vervalt" / "komt te vervallen"
_VERVALT = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)"
    + _LID_ONDERDEEL
    + r"\s+(?:komt\s+te\s+)?verval(?:t|len)\b",
    re.IGNORECASE,
)

# "Artikel 5 komt te luiden:" / "Artikel 36f, eerste lid, komt te luiden:"
_KOMT_TE_LUIDEN = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)" + _LID_ONDERDEEL + r"\s+komt\s+te\s+luiden\b",
    re.IGNORECASE,
)

# "In artikel 5 wordt 'X' vervangen door 'Y'" / "In artikel 5, derde lid, wordt..."
_VERVANGEN_DOOR = re.compile(
    r"\bIn\s+artikel\s+(\d+[a-z]*)" + _LID_ONDERDEEL + r"\s+wordt\b",
    re.IGNORECASE,
)

# Grouped: (pattern, article_group_index, relation, confidence)
_AMENDMENT_PATTERNS: list[tuple[re.Pattern[str], int, str, float]] = [
    (_WORDT_GEWIJZIGD, 1, RELATION_AMENDS, 0.90),
    (_WORDT_INGEVOEGD, 2, RELATION_INTRODUCES, 0.85),
    (_KOMT_TE_LUIDEN, 1, RELATION_AMENDS, 0.85),
    (_VERVALT, 1, RELATION_REPEALS, 0.80),
    (_VERVANGEN_DOOR, 1, RELATION_AMENDS, 0.80),
]


def detect_amendment_citations(
    text: str,
    bwb_id: str,
) -> list[tuple[CitationHit, str]]:
    """Return (CitationHit, relation) pairs for amendment language found in *text*.

    Only call this when *bwb_id* is known — the pipeline enforces that guard.
    Returns a list of (hit, relation_type) tuples.
    """
    if not text or not bwb_id:
        return []

    results: list[tuple[CitationHit, str]] = []
    seen: set[tuple[str, str]] = set()

    for pattern, article_group, relation, confidence in _AMENDMENT_PATTERNS:
        for match in pattern.finditer(text):
            try:
                article_number = match.group(article_group)
            except IndexError:
                continue
            if not article_number:
                continue
            key = (article_number, relation)
            if key in seen:
                continue
            seen.add(key)
            hit = CitationHit(
                kind="article",
                bwb_id=bwb_id,
                article_number=article_number,
                confidence=confidence,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
            results.append((hit, relation))

    return results


class TKAmendmentArticlesSemanticPipeline(SemanticPipelineBase):
    """Detect amendment language and create AMENDS/INTRODUCES/REPEALS edges."""

    def run(self) -> PipelineResult:
        """Scan TK documents for amendment language and create semantic edges."""
        result = PipelineResult()

        # Pre-load the instrument context once before streaming documents.
        amends_index = self._load_amends_instrument_index()

        logger.info(
            "Scanning TK documents for amendment language "
            "(%d with an amended-instrument context).",
            len(amends_index),
        )

        edges = EdgeWriter(self.store, what=None)

        documents = self._load_tk_documents(amends_index)
        for document in self._track(documents, "TK documents"):
            bwb_ids = self._resolve_bwb_ids(document, amends_index)
            if not bwb_ids:
                logger.debug(
                    "Amendment scanner: no BWB id context for document %s — skipping.",
                    document.key,
                )
                result.skipped += 1
                continue

            raw_text = document.props.get("text") or ""
            if not raw_text:
                result.skipped += 1
                continue

            text = strip_xml(str(raw_text))
            if not text:
                result.skipped += 1
                continue

            for bwb_id in bwb_ids:
                hits = detect_amendment_citations(text, bwb_id)
                if not hits:
                    continue

                for hit, relation in hits:
                    key = make_node_key(hit.bwb_id or "", hit.article_number or "")
                    target_node = self._lookup_node(COLLECTION_ARTICLES, key)
                    if target_node is None:
                        logger.debug(
                            "Amendment scanner: no article node found for key=%s — skipping.",
                            key,
                        )
                        continue

                    edge_doc = self._make_edge_doc(
                        from_node=document,
                        to_node=target_node,
                        relation=relation,
                        source=SEMANTIC_SOURCE,
                        confidence=hit.confidence,
                        meta={"reason": "amendment_text", "snippet": hit.snippet},
                        status=EDGE_STATUS_VOORGESTELD,
                    )
                    if edge_doc:
                        edges.add_doc(edge_doc)

        edges.flush_into(result)

        return result

    def _load_tk_documents(self, amends_index: dict[str, list[str]]) -> Iterable[Node]:
        """The TK documents that can hold an amendment: those with a text, and with a law to
        amend (their own ``bwb_id`` or an AMENDS edge). Every other document was read to be
        skipped: 10,085 of 10,085 in a three-week Tweede Kamer."""
        aql = f"""
        FOR doc IN {COLLECTION_DOCUMENTS}
            FILTER "TK" IN doc.labels
            FILTER doc.props.text != null AND doc.props.text != ""
            FILTER doc.props.bwb_id != null OR doc._id IN @amending
            RETURN {slim("doc", "bwb_id", "text")}
        """
        for doc in self.store.query(aql, {"amending": sorted(amends_index)}):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)

    def _load_amends_instrument_index(self) -> dict[str, list[str]]:
        """Build a document-id → [bwb_id, ...] map from document → instrument edges.

        ``semantic tk-amends`` writes one AMENDS edge per (document,
        instrument) pair when a document's title signals legislative amendment
        intent. Loading these once avoids an N-queries-per-document scan inside
        the run loop.
        """
        aql = f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @relation
            FILTER STARTS_WITH(e._from, "{COLLECTION_DOCUMENTS}/")
            FILTER STARTS_WITH(e._to, "{COLLECTION_INSTRUMENTS}/")
            LET inst = DOCUMENT(e._to)
            FILTER inst != null AND inst.props.bwb_id != null
            RETURN {{ document_id: e._from, bwb_id: inst.props.bwb_id }}
        """
        index: dict[str, list[str]] = {}
        for row in self.store.query(aql, {"relation": RELATION_AMENDS}):
            document_id = row.get("document_id")
            bwb_id = row.get("bwb_id")
            if not document_id or not bwb_id:
                continue
            bucket = index.setdefault(str(document_id), [])
            bwb_str = str(bwb_id).strip()
            if bwb_str and bwb_str not in bucket:
                bucket.append(bwb_str)
        return index

    def _resolve_bwb_ids(
        self, document: Node, amends_index: dict[str, list[str]]
    ) -> list[str]:
        """Return all BWB ids that scope the amendment scan for *document*.

        Resolution order:
          1. Direct ``props.bwb_id`` if set.
          2. AMENDS edges from this document to an instrument (built upstream by
             ``semantic tk-amends``).
        """
        bwb_ids: list[str] = []

        bwb_id = document.props.get("bwb_id")
        if bwb_id and isinstance(bwb_id, str):
            stripped = bwb_id.strip()
            if stripped:
                bwb_ids.append(stripped)

        # Edge-based resolution — the common path for hydrated TK documents.
        for edge_bwb_id in amends_index.get(document.arango_id or "", []):
            if edge_bwb_id not in bwb_ids:
                bwb_ids.append(edge_bwb_id)

        return bwb_ids
