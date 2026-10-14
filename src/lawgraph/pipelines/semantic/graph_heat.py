"""``lawgraph semantic graph-heat``: keep the heat of the whole graph in ``lg_heat``.

Counts per window of ``HEAT_WINDOWS`` the nodes with the highest heat, in one pass over
the edges, and replaces what ``lg_heat`` held in one transaction. ``/api/nodes/heat``
without ids reads it there, so a restart of the API reads no edges. Writes no node or
edge: the data version stays as it is.
"""

from __future__ import annotations

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries.overlay import HEAT_MAX_LIMIT, store_heat
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


class GraphHeatSemanticPipeline(PipelineBase):
    store: GraphStore

    def run(self) -> PipelineResult:
        kept = store_heat(self.store, HEAT_MAX_LIMIT)
        logger.info("Kept the heat of %d nodes and windows.", kept)
        return PipelineResult(updated=kept)
