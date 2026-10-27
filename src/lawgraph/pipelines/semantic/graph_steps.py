"""``lawgraph semantic graph-steps``: build the steps between the sources again
(``source_steps``, ``queries/source_steps.py``), whole, from the edges, and put them in place
of the ones there. ``/api/chains`` searches them. Writes no node or edge: the data version
stays as it is.
"""

from __future__ import annotations

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.source_steps import build_source_steps
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class GraphStepsSemanticPipeline(PipelineBase):
    store: GraphStore

    def run(self) -> PipelineResult:
        steps = build_source_steps(self.store)
        logger.info("Built %d steps between the sources.", steps)
        return PipelineResult(updated=steps)
