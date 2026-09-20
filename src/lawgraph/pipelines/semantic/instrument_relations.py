"""Semantic pipelines for instrument-level relations.

AMENDS     — a TK document whose title signals a legislative amendment to a
             known statute (via instrument_aliases).
IMPLEMENTS — an NL statute whose BWB source text contains a CELEX reference,
             linking it to the EU instrument it transposes.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_RAW_SOURCES,
    EDGE_STATUS_VOORGESTELD,
    RAW_KIND_BWB_TOESTAND,
    RELATION_AMENDS,
    RELATION_IMPLEMENTS,
    SOURCE_BWB,
)
from lawgraph.core.aliases import InstrumentAliasMap
from lawgraph.core.identifiers import find_celex_ids
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE_AMENDS = "tk-amends-instrument"
SEMANTIC_SOURCE_IMPLEMENTS = "bwb-implements-directive"

_AMENDS_PATTERN = re.compile(
    r"\bwijziging\s+van\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def detect_amends_instrument(
    title: str | None,
    instrument_aliases: InstrumentAliasMap,
) -> list[tuple[str | None, str | None, float]]:
    """Return (bwb_id, celex, confidence) tuples for instruments the title amends.

    Only fires when the title contains "wijziging van" followed by a known
    instrument name (from instrument_aliases).
    """
    if not title or not _AMENDS_PATTERN.search(title):
        return []

    results: list[tuple[str | None, str | None, float]] = []
    seen: set[tuple[str | None, str | None]] = set()

    # A substring test, not a pattern per name: with thousands of names the patterns fall
    # out of the cache of ``re`` and every title would compile them all again.
    lowered_title = title.lower()
    for label, (bwb_id, celex) in instrument_aliases.items():
        if not (bwb_id or celex):
            continue
        if label.lower() in lowered_title:
            key = (bwb_id, celex)
            if key not in seen:
                seen.add(key)
                results.append((bwb_id, celex, 0.85))

    return results


def detect_celex_references(text: str | None) -> list[str]:
    """Return CELEX IDs found in *text* (numeric CELEX format 3YYYYTNNNN)."""
    if not text:
        return []
    return find_celex_ids(text)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class InstrumentRelationsSemanticPipeline(SemanticPipelineBase):
    """Writes AMENDS edges from bills and IMPLEMENTS edges between instruments."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        result = result.merge(self._run_amends_instrument(since=since))
        result = result.merge(self._run_implements_directive(since=since))
        logger.info("Instrument relations pipeline: %s.", result.summary())
        return result

    # ------------------------------------------------------------------ amends

    def _run_amends_instrument(
        self, since: dt.datetime | None = None
    ) -> PipelineResult:
        result = PipelineResult()
        instrument_aliases = self._load_instrument_aliases()
        if not instrument_aliases:
            logger.warning(
                "No instrument aliases in the graph; skipping AMENDS detection."
            )
            return result

        edge_batch: list[dict] = []
        for doc_node in self._load_tk_documents(since=since):
            title = doc_node.props.get("title") or doc_node.props.get("display_name")
            hits = detect_amends_instrument(
                str(title) if title else None, instrument_aliases
            )
            for bwb_id, celex, confidence in hits:
                target = self._resolve_instrument(bwb_id=bwb_id, celex=celex)
                if not target:
                    continue
                edge_doc = self._make_edge_doc(
                    from_node=doc_node,
                    to_node=target,
                    relation=RELATION_AMENDS,
                    source=SEMANTIC_SOURCE_AMENDS,
                    confidence=confidence,
                    meta={"title": title},
                    status=EDGE_STATUS_VOORGESTELD,
                )
                if edge_doc:
                    edge_batch.append(edge_doc)
                    if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                        created, updated = self._flush_edge_batch(edge_batch, result)
                        result.created += created
                        result.updated += updated
                        edge_batch = []

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info("AMENDS: %s.", result.summary())
        return result

    def _load_tk_documents(self, since: dt.datetime | None = None) -> Iterable[Node]:
        """TK documents — only a bill (Document) may propose a change to a law."""
        since_filter = ""
        bind_vars: dict[str, Any] | None = None
        if since is not None:
            since_filter = "FILTER doc.props.date >= @since"
            bind_vars = {"since": since.isoformat()}

        aql = (
            f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
            '    FILTER "TK" IN doc.labels\n'
            f"    {since_filter}\n"
            "    RETURN doc"
        )
        for doc in self.store.query(aql, bind_vars):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)

    # ------------------------------------------------------------------ implements

    def _run_implements_directive(
        self, since: dt.datetime | None = None
    ) -> PipelineResult:
        result = PipelineResult()
        edge_batch: list[dict] = []

        # First pass: auto-detect CELEX references inside BWB raw texts.
        for bwb_id, raw_text in self._load_bwb_raw_texts(since=since):
            instrument_node = self._resolve_instrument(bwb_id=bwb_id)
            if not instrument_node:
                continue
            for celex in detect_celex_references(raw_text):
                eu_node = self._resolve_instrument(celex=celex)
                if not eu_node:
                    continue
                if eu_node.key == instrument_node.key:
                    continue
                edge_doc = self._make_edge_doc(
                    from_node=instrument_node,
                    to_node=eu_node,
                    relation=RELATION_IMPLEMENTS,
                    source=SEMANTIC_SOURCE_IMPLEMENTS,
                    confidence=0.75,
                    meta={"celex": celex},
                )
                if edge_doc:
                    edge_batch.append(edge_doc)
                    if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                        created, updated = self._flush_edge_batch(edge_batch, result)
                        result.created += created
                        result.updated += updated
                        edge_batch = []

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info("IMPLEMENTS: %s.", result.summary())
        return result

    def _load_bwb_raw_texts(
        self, since: dt.datetime | None = None
    ) -> Iterable[tuple[str, str]]:
        """Yield (bwb_id, raw_text) for each BWB raw_source record."""
        kinds = [RAW_KIND_BWB_TOESTAND]
        bind_vars: dict[str, Any] = {"source": SOURCE_BWB, "kinds": kinds}
        since_filter = ""
        if since is not None:
            since_filter = "FILTER raw.fetched_at >= @since"
            bind_vars["since"] = since.isoformat()
        aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source
            FILTER raw.kind IN @kinds
            FILTER raw.meta.bwb_id != null
            {since_filter}
            RETURN {{ bwb_id: raw.meta.bwb_id, text: raw.payload_text }}
        """
        # Full XML documents (80 KB on average, up to several MB): small batches.
        for row in self.store.query(aql, bind_vars=bind_vars, batch_size=20):
            bwb_id = row.get("bwb_id")
            text = row.get("text")
            if bwb_id and text:
                yield str(bwb_id), str(text)

    # ------------------------------------------------------------------ helpers

    def _resolve_instrument(
        self,
        *,
        bwb_id: str | None = None,
        celex: str | None = None,
    ) -> Node | None:
        if bwb_id:
            return self._lookup_node(COLLECTION_INSTRUMENTS, make_node_key(bwb_id))
        if celex:
            return self._lookup_node(COLLECTION_INSTRUMENTS, make_node_key(celex))
        return None
