"""Semantic pipeline: ``SAME_AS`` between two ``Persoon`` records of the Tweede Kamer of one
person.

The Kamer keeps some people twice: a record with their seats in the Tweede Kamer and a bare one
it made for their seat in the Eerste Kamer (``Functie`` "Eerste Kamerlid"), with no seat, post
or period of its own. The bare member is ``SAME_AS`` the one with a role (``member_role``) of
the same birth date, surname and initials, all three given and equal; one that matches two is
left alone. The page of the bare member is a 301 to the other. Derived in full each run.
"""

from __future__ import annotations

from lawgraph.config.constants import RELATION_SAME_AS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import BASIS_SAME_PERSON
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.sources.addresses import edge_source

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)


class TKPersonDuplicatesSemanticPipeline(SemanticPipelineBase):
    """Write ``SAME_AS`` from a bare member to the member with a role who is the same person."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        pairs = list(self._track(semantic_tk.person_duplicates(self.store), "members"))
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for pair in pairs:
            edges.add(
                pair["from_id"],
                pair["to_id"],
                RELATION_SAME_AS,
                source=EDGE_SOURCE,
                confidence=1.0,
                meta={"basis": BASIS_SAME_PERSON},
            )
        edges.flush_into(result)
        removed = edges.remove_stale(
            RELATION_SAME_AS,
            EDGE_SOURCE,
            semantic_tk.person_duplicate_candidates(self.store, EDGE_SOURCE),
        )
        logger.info(
            "%d member(s) the same person as a member with a role; removed %d SAME_AS no "
            "longer derived.",
            len(pairs),
            removed,
        )
        return result
