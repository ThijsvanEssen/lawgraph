"""``lawgraph semantic graph-steps``: build the steps between the sources again
(``source_steps``, ``queries/source_steps.py``), whole, from the edges, and put them in place
of the ones there. ``/api/chains`` searches them. Writes no node or edge: the data version
stays as it is. Afterwards it searches the chains between the most cited articles, which reads
the steps and their edges into the memory of the database (``warm_chains``).
"""

from __future__ import annotations

import psycopg

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.articles import CITED_BY_INLINE_BELOW, most_cited_articles
from lawgraph.db.queries.chains import warm_chains
from lawgraph.db.queries.source_steps import build_source_steps
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class GraphStepsSemanticPipeline(PipelineBase):
    store: GraphStore

    def run(self) -> PipelineResult:
        steps = build_source_steps(self.store)
        logger.info("Built %d steps between the sources.", steps)
        self._warm_chains()
        return PipelineResult(updated=steps)

    def _warm_chains(self) -> None:
        """The steps are in place: a failed or slow warm-up costs only the warmth."""
        try:
            articles = most_cited_articles(self.store, CITED_BY_INLINE_BELOW)
            warm_chains(self.store, [a["id"] for a in articles])
        except psycopg.Error:
            logger.warning("Searching the chains to warm them failed.", exc_info=True)
