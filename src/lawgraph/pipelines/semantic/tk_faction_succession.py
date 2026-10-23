"""Semantic pipeline: ``CONTINUES`` from a faction to the one it passed all its seats to.

When every holder of a faction's last day who still sits in the Tweede Kamer the day after
sits in one new faction (``core.faction_succession``), the new faction continues the old:
GroenLinks-PvdA ended on 9 June 2026 and PRO began on 10 June with its seats. Read from the
seats alone, never from a name; a faction whose seats do not pass that way has no successor
and none is filled in. Derived in full each run.
"""

from __future__ import annotations

from lawgraph.config.constants import COLLECTION_FACTIONS, RELATION_CONTINUES
from lawgraph.core.faction_succession import Holding, successions
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import REASON_ALL_SEATS
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.sources.addresses import edge_source

from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)


class TKFactionSuccessionSemanticPipeline(SemanticPipelineBase):
    """Write ``CONTINUES`` from a faction to the faction whose seats all passed to it."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = self._track(semantic_tk.faction_holdings(self.store), "seats")
        holdings = [
            Holding(r["person"], r["faction"], r["from_date"], r["to_date"])
            for r in rows
        ]
        found = successions(holdings)
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for succession in found:
            edges.add(
                succession.successor,
                succession.predecessor,
                RELATION_CONTINUES,
                source=EDGE_SOURCE,
                confidence=EXACT_CONFIDENCE,
                meta={
                    "reason": REASON_ALL_SEATS,
                    "effective_date": succession.effective_date,
                    "seats": succession.seats,
                },
            )
        edges.flush_into(result)
        removed = edges.remove_stale(
            RELATION_CONTINUES,
            EDGE_SOURCE,
            sorted({h.faction for h in holdings}),
            to_collections=[COLLECTION_FACTIONS],
        )
        logger.info(
            "%d faction(s) continued by another; removed %d CONTINUES no longer derived.",
            len(found),
            removed,
        )
        return result
