"""Semantic linkage pipeline that connects TK documents to the articles they cite."""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_RAW_SOURCES,
    MAX_SEMANTIC_TEXT_LENGTH,
    RAW_KIND_TK_DOCUMENT,
    RELATION_REFERS_TO,
    SOURCE_TK,
)
from lawgraph.core.aliases import AliasMatcher, InstrumentAliasMap
from lawgraph.core.citations import (
    CitationHit,
    DutchCitationExtractor,
    coerce_text,
    hit_reason,
    make_snippet,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-article-linker"

# ---------------------------------------------------------------------------
# Instrument-level hit collectors
# ---------------------------------------------------------------------------


class NamedActs:
    """The law names of the graph, matched against a text in one pass (``AliasMatcher``)."""

    def __init__(self, aliases: InstrumentAliasMap) -> None:
        self._targets = [
            (bwb_id, celex) for bwb_id, celex in aliases.values() if bwb_id or celex
        ]
        self._matcher = AliasMatcher(
            label for label, (bwb_id, celex) in aliases.items() if bwb_id or celex
        )

    def collect_hits(self, text: str, record: Callable[[CitationHit], None]) -> None:
        for order, start, end in self._matcher.first_matches(text):
            bwb_id, celex = self._targets[order]
            record(
                CitationHit(
                    kind="instrument",
                    bwb_id=bwb_id,
                    celex=celex,
                    confidence=0.6,
                    raw_match=text[start:end],
                    snippet=make_snippet(text, (start, end)),
                )
            )


def detect_tk_citations(
    text: str,
    code_aliases: dict[str, str],
    instrument_aliases: InstrumentAliasMap,
) -> list[CitationHit]:
    """Detect article and instrument citations in the text of a TK document."""
    if not text:
        return []

    return _collect_tk_hits(
        text,
        build_extractor(code_aliases, instrument_aliases),
        NamedActs(instrument_aliases),
    )


def _collect_tk_hits(
    text: str,
    extractor: DutchCitationExtractor,
    named_acts: NamedActs,
) -> list[CitationHit]:
    """Registry-driven article hits plus every instrument-level TK pattern."""
    return detect_in_text(text, extractor, extra=named_acts.collect_hits)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TKSemanticPipeline(SemanticPipelineBase):
    """Pipeline connecting TK documents to the articles and instruments they cite."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

        code_aliases = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not code_aliases and not instrument_aliases:
            logger.warning(
                "No instrument or code aliases configured for TK semantic linking."
            )

        extractor = build_extractor(code_aliases, instrument_aliases)
        named_acts = NamedActs(instrument_aliases)

        logger.info(
            "Processing TK documents for semantic linking (since=%s).",
            describe_since(since),
        )

        edges = EdgeWriter(self.store, what=None)
        doc_count = 0

        documents = self._load_tk_documents(since_iso=since_iso)
        for document in self._track(documents, "TK documents"):
            doc_count += 1
            text = self._extract_document_text(document)
            if not text:
                result.skipped += 1
                continue

            hits = _collect_tk_hits(text, extractor, named_acts)
            if not hits:
                continue

            for hit in hits:
                target_node = self._resolve_target_node(hit)
                if not target_node:
                    continue
                meta = {
                    k: v
                    for k, v in {
                        "raw_match": hit.raw_match,
                        "snippet": hit.snippet,
                        "reason": hit_reason(hit),
                        "qualifier": hit.qualifier,
                    }.items()
                    if v
                }
                edge_doc = self._make_edge_doc(
                    from_node=document,
                    to_node=target_node,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta=meta,
                )
                if edge_doc:
                    edges.add_doc(edge_doc)

        edges.flush_into(result)

        logger.info(
            "TK semantic article linker: processed %d documents, %s.",
            doc_count,
            result.summary(),
        )
        return result

    def _load_tk_documents(self, *, since_iso: str | None = None) -> Iterable[Node]:
        """TK documents; only a Document may be the source of a REFERS_TO edge."""
        bind_vars: dict[str, Any] | None = None
        id_filter = ""
        if since_iso is not None:
            recent_ids = self._recent_external_ids(since_iso)
            if not recent_ids:
                return
            id_filter = "    FILTER doc.props.external_id IN @ids\n"
            bind_vars = {"ids": sorted(recent_ids)}

        aql = (
            f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
            '    FILTER "TK" IN doc.labels\n'
            f"{id_filter}"
            "    RETURN doc"
        )
        for doc in self.store.query(aql, bind_vars=bind_vars):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)

    def _recent_external_ids(self, since_iso: str) -> set[str]:
        """External ids of TK documents fetched at or after *since_iso*."""
        aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source AND raw.kind == @kind
            FILTER raw.fetched_at >= @since
            FILTER raw.external_id != null
        RETURN raw.external_id
        """
        rows = self.store.query(
            aql,
            bind_vars={
                "source": SOURCE_TK,
                "kind": RAW_KIND_TK_DOCUMENT,
                "since": since_iso,
            },
        )
        return {str(row) for row in rows if isinstance(row, str)}

    def _resolve_target_node(self, hit: CitationHit) -> Node | None:
        if hit.kind == "article" and hit.bwb_id and hit.article_number:
            key = make_node_key(hit.bwb_id, hit.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, key)
            if node is None and hit.confidence >= 0.85:
                stub = Node(
                    collection=COLLECTION_ARTICLES,
                    key=key,
                    type=NodeType.ARTICLE,
                    props={
                        "bwb_id": hit.bwb_id,
                        "article_number": hit.article_number,
                        "stub": True,
                        "display_name": f"Artikel {hit.article_number} ({hit.bwb_id})",
                    },
                )
                node, _ = self.store.insert_or_update(stub)
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "TK semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node

        if hit.kind == "article" and hit.celex and hit.article_number:
            key = make_node_key(hit.celex, hit.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, key)
            if node is None and hit.confidence >= 0.85:
                stub = Node(
                    collection=COLLECTION_ARTICLES,
                    key=key,
                    type=NodeType.ARTICLE,
                    props={
                        "celex": hit.celex,
                        "article_number": hit.article_number,
                        "stub": True,
                        "display_name": f"Artikel {hit.article_number} ({hit.celex})",
                    },
                )
                node, _ = self.store.insert_or_update(stub)
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "TK semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node

        if hit.celex:
            key = make_node_key(hit.celex)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for CELEX %s", hit.celex)
            return node

        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for BWB %s", hit.bwb_id)
            return node

        return None

    def _extract_document_text(self, document: Node) -> str | None:
        fragments: list[str] = []
        total_length = 0
        for key in ("title", "summary", "body", "text"):
            candidate = document.props.get(key)
            text_value = coerce_text(candidate)
            if not text_value:
                continue
            fragments.append(text_value)
            total_length += len(text_value)

        total_length = self._collect_raw_text(
            document.props.get("raw"), fragments, total_length
        )
        if not fragments:
            return None
        text = "\n".join(fragments)
        if len(text) >= MAX_SEMANTIC_TEXT_LENGTH:
            logger.debug(
                "TK semantic: document text reached collection limit of %d chars (node %s).",
                MAX_SEMANTIC_TEXT_LENGTH,
                document.key,
            )
        return text

    def _collect_raw_text(
        self,
        value: Any,
        fragments: list[str],
        current_length: int,
    ) -> int:
        if current_length >= MAX_SEMANTIC_TEXT_LENGTH:
            return current_length
        if isinstance(value, str):
            snippet = value.strip()
            if snippet:
                fragments.append(snippet)
                current_length += len(snippet)
        elif isinstance(value, dict):
            current_length = self._collect_from_dict(value, fragments, current_length)
        elif isinstance(value, list):
            current_length = self._collect_from_list(value, fragments, current_length)
        return current_length

    def _collect_from_dict(
        self,
        value: dict[str, Any],
        fragments: list[str],
        current_length: int,
    ) -> int:
        for child in value.values():
            current_length = self._collect_raw_text(child, fragments, current_length)
            if current_length >= MAX_SEMANTIC_TEXT_LENGTH:
                break
        return current_length

    def _collect_from_list(
        self,
        value: list[Any],
        fragments: list[str],
        current_length: int,
    ) -> int:
        for item in value:
            current_length = self._collect_raw_text(item, fragments, current_length)
            if current_length >= MAX_SEMANTIC_TEXT_LENGTH:
                break
        return current_length
