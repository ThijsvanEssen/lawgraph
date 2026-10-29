"""``lawgraph semantic graph-steps``: build the steps between the sources again
(``source_steps``, ``queries/source_steps.py``), whole, from the edges, and put them in place
of the ones there. ``/api/chains`` searches them. Writes no node or edge: the data version
stays as it is. Afterwards it searches the chains between the most cited articles, which reads
the steps and their edges into the memory of the database (``warm_chains``), and opens the
node of each of them as the explorer does (``warm_most_cited_nodes``).
"""

from __future__ import annotations

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.chains import warm_most_cited_chains
from lawgraph.db.queries.source_steps import build_source_steps
from lawgraph.db.queries.warm_nodes import warm_most_cited_nodes
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class GraphStepsSemanticPipeline(PipelineBase):
    store: GraphStore

    def run(self) -> PipelineResult:
        steps = build_source_steps(self.store)
        logger.info("Built %d steps between the sources.", steps)
        warm_most_cited_chains(self.store)
        warm_most_cited_nodes(self.store)
        return PipelineResult(updated=steps)
