"""Semantic pipelines for instrument-level relations.

AMENDS_INSTRUMENT  — TK publication/procedure whose title signals a legislative
                     amendment to a known statute (via instrument_aliases).
IMPLEMENTS_DIRECTIVE — NL statute whose BWB source text contains a CELEX
                       reference, linking it to the EU instrument it transposes.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
    RAW_KIND_BWB_REGELING,
    RAW_KIND_BWB_TOESTAND,
    RELATION_AMENDS_INSTRUMENT,
    RELATION_DISCUSSES,
    RELATION_IMPLEMENTS_DIRECTIVE,
    SOURCE_BWB,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key

from .base import InstrumentAliasMap, SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE_AMENDS = "tk-amends-instrument"
SEMANTIC_SOURCE_IMPLEMENTS = "bwb-implements-directive"

_AMENDS_PATTERN = re.compile(
    r"\bwijziging\s+van\b",
    re.IGNORECASE,
)
_CELEX_PATTERN = re.compile(r"\b3\d{4}[CLRDF]\d{4}\b", re.IGNORECASE)


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

    for label, (bwb_id, celex) in instrument_aliases.items():
        if not (bwb_id or celex):
            continue
        if re.search(re.escape(label), title, re.IGNORECASE):
            key = (bwb_id, celex)
            if key not in seen:
                seen.add(key)
                results.append((bwb_id, celex, 0.85))

    return results


def detect_celex_references(text: str | None) -> list[str]:
    """Return CELEX IDs found in *text* (numeric CELEX format 3YYYYTNNNN)."""
    if not text:
        return []
    return [m.group(0).upper() for m in _CELEX_PATTERN.finditer(text)]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class InstrumentRelationsPipeline(SemanticPipelineBase):
    """Writes AMENDS_INSTRUMENT and IMPLEMENTS_DIRECTIVE edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        result = result.merge(self._run_amends_instrument(since=since))
        result = result.merge(self._run_implements_directive(since=since))
        result = result.merge(self._run_discusses_instrument(since=since))
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
                "No instrument_aliases configured; skipping AMENDS_INSTRUMENT detection."
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
                    relation=RELATION_AMENDS_INSTRUMENT,
                    source=SEMANTIC_SOURCE_AMENDS,
                    confidence=confidence,
                    meta={"title": title},
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

        logger.info("AMENDS_INSTRUMENT: %s.", result.summary())
        return result

    # ------------------------------------------------------------------ discusses

    def _run_discusses_instrument(
        self, since: dt.datetime | None = None
    ) -> PipelineResult:
        """Write DISCUSSES edges from TK procedures that discuss a known instrument.

        DISCUSSES is a weaker relation than AMENDS — it means the procedure
        references or debates the instrument but does not necessarily change it.
        Only procedures (TK Zaken) are linked; publications get MENTIONS_INSTRUMENT
        via the TK article semantic pipeline instead.

        Performance: instead of an O(procedures × aliases) double loop with
        re.search per combination, we build a single combined OR-pattern from
        all alias labels and scan each title once, then resolve only the
        matched aliases. This cuts regex evaluations from M×N to N.
        """
        result = PipelineResult()
        instrument_aliases = self._load_instrument_aliases()
        if not instrument_aliases:
            logger.debug(
                "No instrument_aliases configured; skipping DISCUSSES detection."
            )
            return result

        # Pre-compile a combined pattern: one search surfaces all matches.
        alias_labels = [
            label
            for label, (bwb, celex) in instrument_aliases.items()
            if (bwb or celex)
        ]
        if not alias_labels:
            return result
        sorted_labels = sorted(alias_labels, key=len, reverse=True)
        combined_pattern = re.compile(
            "|".join(re.escape(lbl) for lbl in sorted_labels), re.IGNORECASE
        )

        since_filter = ""
        bind_vars: dict[str, Any] = {}
        if since is not None:
            since_filter = (
                "FILTER doc.props.datum >= @since OR doc.props.fetched_at >= @since"
            )
            bind_vars["since"] = since.isoformat()

        aql = (
            f"FOR doc IN {COLLECTION_PROCEDURES}\n"
            '    FILTER "TK" IN doc.labels\n'
            f"    {since_filter}\n"
            "    RETURN doc"
        )
        edge_batch: list[dict] = []
        for doc in self.store.query(aql, bind_vars or None):
            proc_node = Node.from_document(COLLECTION_PROCEDURES, doc)
            title = (
                proc_node.props.get("title")
                or proc_node.props.get("display_name")
                or ""
            )
            if not title:
                continue

            matched_labels = {m.group(0) for m in combined_pattern.finditer(title)}
            if not matched_labels:
                continue

            for label in matched_labels:
                # Resolve the canonical label (case-insensitive match).
                pair = next(
                    (
                        v
                        for k, v in instrument_aliases.items()
                        if k.lower() == label.lower()
                    ),
                    None,
                )
                if pair is None:
                    continue
                bwb_id, celex = pair
                if not (bwb_id or celex):
                    continue
                target = self._resolve_instrument(bwb_id=bwb_id, celex=celex)
                if not target:
                    continue
                edge_doc = self._make_edge_doc(
                    from_node=proc_node,
                    to_node=target,
                    relation=RELATION_DISCUSSES,
                    source="tk-procedure-discusses",
                    confidence=0.7,
                    meta={"title": title, "matched_alias": label},
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

        logger.info("DISCUSSES: %s.", result.summary())
        return result

    def _load_tk_documents(self, since: dt.datetime | None = None) -> Iterable[Node]:
        since_filter = ""
        bind_vars: dict[str, Any] | None = None
        if since is not None:
            since_filter = (
                "FILTER doc.props.datum >= @since OR doc.props.fetched_at >= @since"
            )
            bind_vars = {"since": since.isoformat()}

        for collection in (COLLECTION_PUBLICATIONS, COLLECTION_PROCEDURES):
            aql = (
                f"FOR doc IN {collection}\n"
                '    FILTER "TK" IN doc.labels\n'
                f"    {since_filter}\n"
                "    RETURN doc"
            )
            for doc in self.store.query(aql, bind_vars):
                yield Node.from_document(collection, doc)

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
                    relation=RELATION_IMPLEMENTS_DIRECTIVE,
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

        logger.info("IMPLEMENTS_DIRECTIVE: %s.", result.summary())
        return result

    def _load_bwb_raw_texts(
        self, since: dt.datetime | None = None
    ) -> Iterable[tuple[str, str]]:
        """Yield (bwb_id, raw_text) for each BWB raw_source record."""
        kinds = [RAW_KIND_BWB_REGELING, RAW_KIND_BWB_TOESTAND]
        bind_vars: dict[str, Any] = {"source": SOURCE_BWB, "kinds": kinds}
        since_filter = ""
        if since is not None:
            since_filter = "FILTER raw.fetched_at >= @since"
            bind_vars["since"] = since.isoformat()
        aql = f"""
        FOR raw IN raw_sources
            FILTER raw.source == @source
            FILTER raw.kind IN @kinds
            FILTER raw.meta.bwb_id != null
            {since_filter}
            RETURN {{ bwb_id: raw.meta.bwb_id, text: raw.payload_text }}
        """
        for row in self.store.query(aql, bind_vars=bind_vars):
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
            return self.store.get_node(COLLECTION_INSTRUMENTS, make_node_key(bwb_id))
        if celex:
            return self.store.get_node(COLLECTION_INSTRUMENTS, make_node_key(celex))
        return None


# ---------------------------------------------------------------------------
# Public detection helpers (used by tests and CLI)
# ---------------------------------------------------------------------------


def build_instrument_alias_map(raw: dict[str, Any]) -> InstrumentAliasMap:
    """Parse a raw profile instrument_aliases dict into an InstrumentAliasMap."""
    return SemanticPipelineBase._parse_instrument_aliases(raw)
