"""``semantic bwb-implements``: a Dutch regulation that names an EU act implements it.

IMPLEMENTS from a BWB regulation to every EU instrument in the graph whose CELEX number
its text names. ``normalize bwb`` keeps those numbers on the regulation
(``props.celex_refs``), so no toestand is read here.
"""

from __future__ import annotations

from typing import Iterable

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    RELATION_IMPLEMENTS,
    SOURCE_BWB,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import EdgeWriter

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE_IMPLEMENTS = "bwb-implements-directive"


class BWBImplementsSemanticPipeline(SemanticPipelineBase):
    """IMPLEMENTS edges from regulations to the EU acts they name."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None)

        # The CELEX numbers a regulation names: ``normalize bwb`` keeps them on the node.
        regulations = self._load_celex_references()
        for bwb_id, celex_refs in self._track(
            regulations, "regulations naming EU acts"
        ):
            instrument_node = self._resolve_instrument(bwb_id=bwb_id)
            if not instrument_node:
                continue
            for celex in celex_refs:
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
                    edges.add_doc(edge_doc)

        edges.flush_into(result)

        return result

    def _load_celex_references(self) -> Iterable[tuple[str, list[str]]]:
        """``(bwb_id, CELEX numbers)`` of the regulations that name an EU act."""
        aql = f"""
        FOR regulation IN {COLLECTION_INSTRUMENTS}
            FILTER regulation.props.source == @source
            FILTER LENGTH(regulation.props.celex_refs) > 0
            RETURN [regulation.props.bwb_id, regulation.props.celex_refs]
        """
        for bwb_id, celex_refs in self.store.query(aql, {"source": SOURCE_BWB}):
            if bwb_id:
                yield str(bwb_id), list(celex_refs)
