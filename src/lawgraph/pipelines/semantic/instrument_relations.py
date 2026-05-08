"""Semantic pipelines for instrument-level relations.

AMENDS_INSTRUMENT  — TK publication/procedure whose title signals a legislative
                     amendment to a known statute (via instrument_aliases).
IMPLEMENTS_DIRECTIVE — NL statute whose BWB source text contains a CELEX
                       reference, linking it to the EU instrument it transposes.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from lawgraph.config.settings import (  # noqa: F401 – kept for future use
    COLLECTION_INSTRUMENT_ARTICLES,
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
from lawgraph.logging import get_logger
from lawgraph.models import Node, PipelineResult, make_node_key

from .base import InstrumentAliasMap, SemanticPipelineBase, _parse_instrument_aliases

logger = get_logger(__name__)

SEMANTIC_SOURCE_AMENDS = "tk-amends-instrument"
SEMANTIC_SOURCE_IMPLEMENTS = "bwb-implements-directive"

_AMENDS_PATTERN = re.compile(
    r"\bwijziging\s+van\b",
    re.IGNORECASE,
)
_CELEX_PATTERN = re.compile(r"\b3\d{4}[LRD]\d{4}\b", re.IGNORECASE)


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

    def run(self, **_kwargs: Any) -> PipelineResult:  # type: ignore[override]
        result = PipelineResult()
        result = result.merge(self._run_amends_instrument())
        result = result.merge(self._run_implements_directive())
        result = result.merge(self._run_discusses_instrument())
        logger.info("Instrument relations pipeline: %s.", result.summary())
        return result

    # ------------------------------------------------------------------ amends

    def _run_amends_instrument(self) -> PipelineResult:
        result = PipelineResult()
        instrument_aliases = self._load_instrument_aliases()
        if not instrument_aliases:
            logger.warning(
                "No instrument_aliases configured; skipping AMENDS_INSTRUMENT detection."
            )
            return result

        for doc_node in self._load_tk_documents():
            title = doc_node.props.get("title") or doc_node.props.get("display_name")
            hits = detect_amends_instrument(
                str(title) if title else None, instrument_aliases
            )
            for bwb_id, celex, confidence in hits:
                target = self._resolve_instrument(bwb_id=bwb_id, celex=celex)
                if not target:
                    continue
                created = self._create_semantic_edge(
                    from_node=doc_node,
                    to_node=target,
                    relation=RELATION_AMENDS_INSTRUMENT,
                    source=SEMANTIC_SOURCE_AMENDS,
                    confidence=confidence,
                    meta={"title": title},
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info("AMENDS_INSTRUMENT: %s.", result.summary())
        return result

    # ------------------------------------------------------------------ discusses

    def _run_discusses_instrument(self) -> PipelineResult:
        """Write DISCUSSES edges from TK procedures that discuss a known instrument.

        DISCUSSES is a weaker relation than AMENDS — it means the procedure
        references or debates the instrument but does not necessarily change it.
        Only procedures (TK Zaken) are linked; publications get MENTIONS_INSTRUMENT
        via the TK article semantic pipeline instead.
        """
        result = PipelineResult()
        instrument_aliases = self._load_instrument_aliases()
        if not instrument_aliases:
            logger.debug(
                "No instrument_aliases configured; skipping DISCUSSES detection."
            )
            return result

        aql = (
            f"FOR doc IN {COLLECTION_PROCEDURES}\n"
            '    FILTER "TK" IN doc.labels\n'
            "    RETURN doc"
        )
        for doc in self.store.query(aql):
            proc_node = Node.from_document(COLLECTION_PROCEDURES, doc)
            title = (
                proc_node.props.get("title")
                or proc_node.props.get("display_name")
                or ""
            )
            if not title:
                continue

            for label, (bwb_id, celex) in instrument_aliases.items():
                if not (bwb_id or celex):
                    continue
                if not re.search(re.escape(label), title, re.IGNORECASE):
                    continue
                target = self._resolve_instrument(bwb_id=bwb_id, celex=celex)
                if not target:
                    continue
                created = self._create_semantic_edge(
                    from_node=proc_node,
                    to_node=target,
                    relation=RELATION_DISCUSSES,
                    source="tk-procedure-discusses",
                    confidence=0.7,
                    meta={"title": title, "matched_alias": label},
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info("DISCUSSES: %s.", result.summary())
        return result

    def _load_tk_documents(self) -> Iterable[Node]:
        for collection in (COLLECTION_PUBLICATIONS, COLLECTION_PROCEDURES):
            aql = (
                f"FOR doc IN {collection}\n"
                '    FILTER "TK" IN doc.labels\n'
                "    RETURN doc"
            )
            for doc in self.store.query(aql):
                yield Node.from_document(collection, doc)

    # ------------------------------------------------------------------ implements

    def _run_implements_directive(self) -> PipelineResult:
        result = PipelineResult()

        # First pass: auto-detect CELEX references inside BWB raw texts.
        for bwb_id, raw_text in self._load_bwb_raw_texts():
            instrument_node = self._resolve_instrument(bwb_id=bwb_id)
            if not instrument_node:
                continue
            for celex in detect_celex_references(raw_text):
                eu_node = self._resolve_instrument(celex=celex)
                if not eu_node:
                    continue
                if eu_node.key == instrument_node.key:
                    continue
                created = self._create_semantic_edge(
                    from_node=instrument_node,
                    to_node=eu_node,
                    relation=RELATION_IMPLEMENTS_DIRECTIVE,
                    source=SEMANTIC_SOURCE_IMPLEMENTS,
                    confidence=0.75,
                    meta={"celex": celex},
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        # Second pass: explicit profile-level implements mappings (nl_id → eu_celex).
        config = self._load_domain_config()
        for entry in config.get("implements", []):
            nl_id = entry.get("nl_id")
            eu_celex = entry.get("eu_celex")
            if not nl_id or not eu_celex:
                continue
            nl_node = self.store.get_node(COLLECTION_INSTRUMENTS, make_node_key(nl_id))
            eu_node = self._resolve_instrument(celex=eu_celex)
            if not nl_node or not eu_node:
                continue
            created = self._create_semantic_edge(
                from_node=nl_node,
                to_node=eu_node,
                relation=RELATION_IMPLEMENTS_DIRECTIVE,
                source="profile-implements",
                confidence=1.0,
                meta={"celex": eu_celex},
                result=result,
            )
            if created:
                result.created += 1
            else:
                result.updated += 1

        logger.info("IMPLEMENTS_DIRECTIVE: %s.", result.summary())
        return result

    def _load_bwb_raw_texts(self) -> Iterable[tuple[str, str]]:
        """Yield (bwb_id, raw_text) for each BWB raw_source record."""
        kinds = [RAW_KIND_BWB_REGELING, RAW_KIND_BWB_TOESTAND]
        bind_vars: dict[str, Any] = {"source": SOURCE_BWB, "kinds": kinds}
        aql = """
        FOR raw IN raw_sources
            FILTER raw.source == @source
            FILTER raw.kind IN @kinds
            FILTER raw.meta.bwb_id != null
            RETURN { bwb_id: raw.meta.bwb_id, text: raw.payload_text }
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
    return _parse_instrument_aliases(raw)
