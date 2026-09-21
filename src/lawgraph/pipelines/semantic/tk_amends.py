"""``semantic tk-amends``: a Tweede Kamer document that amends a law, by its title.

AMENDS from a TK document whose title signals a legislative amendment ("Wijziging van
de ...") to a statute that is in the graph, found through the instrument aliases. The edges
are what ``semantic tk-amendment-articles`` starts from.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
)
from lawgraph.core.aliases import InstrumentAliasMap
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase, slim

logger = get_logger(__name__)

SEMANTIC_SOURCE_AMENDS = "tk-amends-instrument"

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


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TKAmendsSemanticPipeline(SemanticPipelineBase):
    """AMENDS edges from bills to the instruments their title says they change."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        instrument_aliases = self._load_instrument_aliases()
        if not instrument_aliases:
            logger.warning(
                "No instrument aliases in the graph; skipping AMENDS detection."
            )
            return result

        edges = EdgeWriter(self.store, what=None)
        documents = self._load_tk_documents(since=since)
        for doc_node in self._track(documents, "TK documents"):
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
                    edges.add_doc(edge_doc)

        edges.flush_into(result)

        return result

    def _load_tk_documents(self, since: dt.datetime | None = None) -> Iterable[Node]:
        """TK documents — only a bill (Document) may propose a change to a law."""
        since_filter = ""
        bind_vars: dict[str, Any] | None = None
        if since is not None:
            since_filter = "FILTER doc.props.date >= @since"
            # props.date is a date; a timestamp of the same day sorts after it.
            bind_vars = {"since": since.date().isoformat()}

        aql = (
            f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
            '    FILTER "TK" IN doc.labels\n'
            f"    {since_filter}\n"
            f"    RETURN {slim('doc', 'title', 'display_name')}"
        )
        for doc in self.store.query(aql, bind_vars):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)
