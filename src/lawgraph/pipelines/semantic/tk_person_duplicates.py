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
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.db.store import edge_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-person-duplicates"


class TKPersonDuplicatesSemanticPipeline(SemanticPipelineBase):
    """Write ``SAME_AS`` from a bare member to the member with a role who is the same person."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        pairs = list(self._track(semantic_tk.person_duplicates(self.store), "members"))
        kept: dict[str, set[str]] = {}
        edges = EdgeWriter(self.store, what=None)
        for pair in pairs:
            if edges.add(
                pair["from_id"],
                pair["to_id"],
                RELATION_SAME_AS,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"basis": "birth_date_surname_initials"},
            ):
                kept.setdefault(pair["from_id"], set()).add(
                    edge_key(pair["from_id"], RELATION_SAME_AS, pair["to_id"])
                )
        edges.flush_into(result)
        removed = semantic_edges.remove_edges_from(
            self.store,
            RELATION_SAME_AS,
            SEMANTIC_SOURCE,
            semantic_tk.person_duplicate_candidates(self.store, SEMANTIC_SOURCE),
            kept,
        )
        logger.info(
            "%d member(s) the same person as a member with a role; removed %d SAME_AS no "
            "longer derived.",
            len(pairs),
            removed,
        )
        return result
