"""Semantic pipeline that detects legislative amendment language in TK publications."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from lawgraph.config.constants import (
    BWB_ID_PREFIX,
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_KAMERSTUKDOSSIERS,
    COLLECTION_PUBLICATIONS,
    EDGE_STATUS_CANONIEK,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS_INSTRUMENT,
    RELATION_DEEL_VAN_DOSSIER,
    RELATION_INTRODUCEERT,
    RELATION_TREKT_IN,
    RELATION_WIJZIGT,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.semantic.base import SemanticPipelineBase
from lawgraph.pipelines.semantic.citation_detect import (
    CitationHit,
    make_snippet,
    strip_xml,
)

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

# "Artikel 5 vervalt" / "Artikel 5, eerste lid, onder d, vervalt"
_VERVALT = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)" + _LID_ONDERDEEL + r"\s+(?:komt\s+te\s+)?vervalt?\b",
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
    (_WORDT_GEWIJZIGD, 1, RELATION_WIJZIGT, 0.90),
    (_WORDT_INGEVOEGD, 2, RELATION_INTRODUCEERT, 0.85),
    (_KOMT_TE_LUIDEN, 1, RELATION_WIJZIGT, 0.85),
    (_VERVALT, 1, RELATION_TREKT_IN, 0.80),
    (_VERVANGEN_DOOR, 1, RELATION_WIJZIGT, 0.80),
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


class AmendmentArticlePipeline(SemanticPipelineBase):
    """Detect legislative amendment language and create WIJZIGT/INTRODUCEERT/TREKT_IN edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Scan TK publications for amendment language and create semantic edges."""
        result = PipelineResult()

        # Pre-load indexes before streaming documents.
        amends_index = self._load_amends_instrument_index()
        open_pub_ids = self._load_open_publication_ids()

        logger.info(
            "Scanning TK publications for amendment language (%d with "
            "AMENDS_INSTRUMENT context, %d from open dossiers, since=%s).",
            len(amends_index),
            len(open_pub_ids),
            since,
        )

        edge_batch: list[dict[str, Any]] = []
        doc_count = 0

        for document in self._load_tk_publications(since=since):
            doc_count += 1
            bwb_ids = self._resolve_bwb_ids(document, amends_index)
            if not bwb_ids:
                logger.debug(
                    "Amendment scanner: no BWB id context for document %s — skipping.",
                    document.key,
                )
                result.skipped += 1
                continue

            raw_text = document.props.get("text") or document.props.get("raw_xml") or ""
            if not raw_text:
                result.skipped += 1
                continue

            text = strip_xml(str(raw_text))
            if not text:
                result.skipped += 1
                continue

            edge_status = (
                EDGE_STATUS_VOORGESTELD
                if document.id in open_pub_ids
                else EDGE_STATUS_CANONIEK
            )

            for bwb_id in bwb_ids:
                hits = detect_amendment_citations(text, bwb_id)
                if not hits:
                    continue

                for hit, relation in hits:
                    key = make_node_key(hit.bwb_id or "", hit.article_number or "")
                    target_node = self.store.get_node(
                        COLLECTION_INSTRUMENT_ARTICLES, key
                    )
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
                        status=edge_status,
                    )
                    if edge_doc:
                        edge_batch.append(edge_doc)
                        if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                            created, updated = self._flush_edge_batch(
                                edge_batch, result
                            )
                            result.created += created
                            result.updated += updated
                            edge_batch = []

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info(
            "Amendment article linker: processed %d documents, %s.",
            doc_count,
            result.summary(),
        )
        return result

    def _load_tk_publications(
        self, *, since: dt.datetime | None = None
    ) -> Iterable[Node]:
        since_iso: str | None = None
        if since is not None:
            since_iso = iso_timestamp(since)

        if since_iso is not None:
            aql = (
                f"FOR doc IN {COLLECTION_PUBLICATIONS}\n"
                '    FILTER "TK" IN doc.labels\n'
                "    FILTER doc.props.fetched_at >= @since\n"
                "    RETURN doc"
            )
            for doc in self.store.query(aql, bind_vars={"since": since_iso}):
                yield Node.from_document(COLLECTION_PUBLICATIONS, doc)
        else:
            aql = (
                f"FOR doc IN {COLLECTION_PUBLICATIONS}\n"
                '    FILTER "TK" IN doc.labels\n'
                "    RETURN doc"
            )
            for doc in self.store.query(aql):
                yield Node.from_document(COLLECTION_PUBLICATIONS, doc)

    def _load_amends_instrument_index(self) -> dict[str, list[str]]:
        """Build a publication-id → [bwb_id, ...] map from AMENDS_INSTRUMENT edges.

        The instrument_relations pipeline writes one AMENDS_INSTRUMENT edge per
        (publication, instrument) pair when a publication's title signals
        legislative amendment intent. By loading these once we avoid an
        N-queries-per-document scan inside the run loop.
        """
        aql = f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @relation
            FILTER STARTS_WITH(e._from, "{COLLECTION_PUBLICATIONS}/")
            LET inst = DOCUMENT(e._to)
            FILTER inst != null AND inst.props.bwb_id != null
            RETURN {{ pub_id: e._from, bwb_id: inst.props.bwb_id }}
        """
        index: dict[str, list[str]] = {}
        for row in self.store.query(aql, {"relation": RELATION_AMENDS_INSTRUMENT}):
            pub_id = row.get("pub_id")
            bwb_id = row.get("bwb_id")
            if not pub_id or not bwb_id:
                continue
            bucket = index.setdefault(str(pub_id), [])
            bwb_str = str(bwb_id).strip()
            if bwb_str and bwb_str not in bucket:
                bucket.append(bwb_str)
        return index

    def _load_open_publication_ids(self) -> set[str]:
        """Return IDs of publications whose dossier is not yet afgedaan.

        A single AQL traversal follows DEEL_VAN_DOSSIER edges from publications
        to their kamerstukdossier and filters on afgedaan == false.
        """
        aql = f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == @relation
            FILTER STARTS_WITH(e._from, "{COLLECTION_PUBLICATIONS}/")
            FILTER STARTS_WITH(e._to, "{COLLECTION_KAMERSTUKDOSSIERS}/")
            LET dossier = DOCUMENT(e._to)
            FILTER dossier != null AND dossier.props.afgedaan == false
            RETURN DISTINCT e._from
        """
        return {
            str(row)
            for row in self.store.query(aql, {"relation": RELATION_DEEL_VAN_DOSSIER})
        }

    def _resolve_bwb_ids(
        self, document: Node, amends_index: dict[str, list[str]]
    ) -> list[str]:
        """Return all BWB ids that scope the amendment scan for *document*.

        Resolution order:
          1. Direct ``props.bwb_id`` if set.
          2. ``props.code_aliases`` mapping containing BWBR* values.
          3. AMENDS_INSTRUMENT edges from this publication (built upstream by
             the instrument_relations pipeline).
        """
        bwb_ids: list[str] = []

        bwb_id = document.props.get("bwb_id")
        if bwb_id and isinstance(bwb_id, str):
            stripped = bwb_id.strip()
            if stripped:
                bwb_ids.append(stripped)

        code_aliases = document.props.get("code_aliases")
        if isinstance(code_aliases, dict):
            for value in code_aliases.values():
                if isinstance(value, str) and value.upper().startswith(BWB_ID_PREFIX):
                    stripped = value.strip()
                    if stripped and stripped not in bwb_ids:
                        bwb_ids.append(stripped)

        # Edge-based fallback — the common path for hydrated TK publications.
        for edge_bwb_id in amends_index.get(document.id or "", []):
            if edge_bwb_id not in bwb_ids:
                bwb_ids.append(edge_bwb_id)

        return bwb_ids
