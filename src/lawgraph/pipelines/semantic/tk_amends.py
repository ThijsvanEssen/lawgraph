"""``semantic tk-amends``: a Tweede Kamer document that amends a law, by its title.

AMENDS from an amendement, the text of a bill or its memorandum (``tk_records.kinds.may_amend``)
whose title signals a legislative amendment ("Wijziging van de ...") to a statute that is in
the graph, found through the instrument aliases. The edges are what ``semantic
tk-amendment-articles`` starts from. A document that is read loses the edges of this step it
no longer gets: a motie on a bill's dossier carries the bill's title and amends nothing.

Two names in such a title are no law the bill amends: an EU act it implements ("in verband
met de implementatie van Verordening (EU) 2023/2869"; a Dutch bill cannot amend EU law), and
the act it makes itself, whose citeertitel closes the title ("(Wet implementatie Europees
centraal toegangspunt)"): the instrument ``LEGISLATED_IN`` the document's dossier, once that
act is published and loaded. Every run removes such an edge of any document, also of one not
read again since its act was published.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
)
from lawgraph.core.citations import CitationHit
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.tk_records.kinds import may_amend
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk

from .base import SemanticPipelineBase
from .tk import NamedActs

logger = get_logger(__name__)

EDGE_SOURCE = "tk-amends-instrument"
AMENDS_CONFIDENCE = 0.85

_AMENDS_PATTERN = re.compile(
    r"\bwijziging\s+van\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def detect_amends_instrument(
    title: str | None, named_acts: NamedActs
) -> list[tuple[str | None, str | None, float]]:
    """``(bwb_id, celex, confidence)`` of each law a title that says "wijziging van" names
    (*named_acts*: by its name, as a whole word)."""
    if not title or not _AMENDS_PATTERN.search(title):
        return []
    named: list[CitationHit] = []
    named_acts.collect_hits(title, named.append)
    laws = dict.fromkeys((hit.bwb_id, hit.celex) for hit in named)
    return [(bwb_id, celex, AMENDS_CONFIDENCE) for bwb_id, celex in laws]


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
        named_acts = NamedActs(instrument_aliases)

        edges = EdgeWriter(self.store, what=None, remembers=True)
        read: set[str] = set()
        acts = semantic_tk.acts_of_dossiers(self.store)
        documents = self._load_tk_documents(since=since)
        for doc_node in self._track(documents, "TK documents"):
            read.add(doc_node.node_id or "")
            own_acts = semantic_tk.own_acts(acts, doc_node.props)
            for edge_doc in self._amends_edges(doc_node, named_acts, own_acts):
                edges.add_doc(edge_doc)

        edges.flush_into(result)
        removed = edges.remove_stale(RELATION_AMENDS, EDGE_SOURCE, sorted(read))
        logger.info("Removed %d AMENDS edges no longer derived.", removed)
        # A document read before its act was published (and not read since) still has them.
        own = semantic_tk.remove_own_act_edges(
            self.store, [RELATION_AMENDS], EDGE_SOURCE
        )
        logger.info(
            "Removed %d AMENDS edges to the act of the paper's own dossier.", own
        )
        return result

    def _amends_edges(
        self,
        doc_node: Node,
        named_acts: NamedActs,
        own_acts: set[str],
    ) -> Iterator[dict[str, Any]]:
        """The AMENDS edges of one document; none unless its kind can amend a law, none to
        an EU act and none to an act of its own dossier (*own_acts*, instrument ids)."""
        if not may_amend(doc_node.props.get("kind")):
            return
        # An amendement is named by its own subject; the dossier's title says which law
        # the bill it was submitted on changes.
        title = (
            doc_node.props.get("dossier_title")
            or doc_node.props.get("title")
            or doc_node.props.get("display_name")
        )
        hits = detect_amends_instrument(str(title) if title else None, named_acts)
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
                source=EDGE_SOURCE,
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
