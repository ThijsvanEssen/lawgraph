"""``semantic tk-amends``: a Tweede Kamer document that amends a law, by its title.

AMENDS from an amendement, the text of a bill or its memorandum (``tk_records.may_amend``)
whose title signals a legislative amendment ("Wijziging van de ...") to a statute that is in
the graph, found through the instrument aliases. The edges are what ``semantic
tk-amendment-articles`` starts from. A document that is read loses the edges of this step it
no longer gets: a motie on a bill's dossier carries the bill's title and amends nothing.

Two names in such a title are no law the bill amends: an EU act it implements ("in verband
met de implementatie van Verordening (EU) 2023/2869"; a Dutch bill cannot amend EU law), and
the act it makes itself, whose citeertitel closes the title ("(Wet implementatie Europees
centraal toegangspunt)"): the instrument ``LEGISLATED_IN`` the document's dossier, once that
act is published and loaded.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Iterator

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
)
from lawgraph.core import tk_records
from lawgraph.core.aliases import InstrumentAliasMap
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import tk as semantic_tk

from .base import SemanticPipelineBase

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
    """AMENDS edges from bills and amendementen to the instruments their title says they
    change."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        instrument_aliases = self._load_instrument_aliases()
        if not instrument_aliases:
            logger.warning(
                "No instrument aliases in the graph; skipping AMENDS detection."
            )
            return result

        edges = EdgeWriter(self.store, what=None)
        kept: dict[str, set[str]] = {}
        acts = semantic_tk.acts_of_dossiers(self.store)
        documents = self._load_tk_documents(since=since)
        for doc_node in self._track(documents, "TK documents"):
            keys = kept.setdefault(doc_node.node_id or "", set())
            own_acts = {
                act
                for label in doc_node.props.get("dossier_numbers") or []
                for act in acts.get(str(label), ())
            }
            for edge_doc in self._amends_edges(doc_node, instrument_aliases, own_acts):
                keys.add(edge_doc["_key"])
                edges.add_doc(edge_doc)

        edges.flush_into(result)
        removed = semantic_edges.remove_edges_from(
            self.store, RELATION_AMENDS, SEMANTIC_SOURCE_AMENDS, sorted(kept), kept
        )
        logger.info("Removed %d AMENDS edges no longer derived.", removed)
        return result

    def _amends_edges(
        self,
        doc_node: Node,
        instrument_aliases: InstrumentAliasMap,
        own_acts: set[str],
    ) -> Iterator[dict[str, Any]]:
        """The AMENDS edges of one document; none unless its kind can amend a law, none to
        an EU act and none to an act of its own dossier (*own_acts*, instrument ids)."""
        if not tk_records.may_amend(doc_node.props.get("kind")):
            return
        # An amendement is named by its own subject; the dossier's title says which law
        # the bill it was submitted on changes.
        title = (
            doc_node.props.get("dossier_title")
            or doc_node.props.get("title")
            or doc_node.props.get("display_name")
        )
        hits = detect_amends_instrument(
            str(title) if title else None, instrument_aliases
        )
        for bwb_id, celex, confidence in hits:
            if not bwb_id:  # an EU act: implemented, not amended
                continue
            target = self._resolve_instrument(bwb_id=bwb_id, celex=celex)
            if not target or target.node_id in own_acts:
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
                yield edge_doc

    def _load_tk_documents(self, since: dt.datetime | None = None) -> Iterable[Node]:
        """The TK documents with their kind and title; a Case never proposes a change."""
        # props.date is a date; a timestamp of the same day sorts after it.
        since_date = since.date().isoformat() if since is not None else None
        for doc in semantic_tk.tk_document_titles(self.store, since_date):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)
