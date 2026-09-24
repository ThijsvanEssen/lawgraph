"""Write the relations between dossiers of different numbers, from the graph.

``RELATED_TO`` is the Kamer's own relation between two cases (``Zaak.GerelateerdNaar``,
stored on the case by ``normalize tk``) lifted to their dossiers; ``REVISES`` and
``ACCOMPANIES`` follow from the titles of the budget laws. The rules are
:mod:`lawgraph.core.dossier_relations`.

Runs over every dossier and every related case, since a dossier loaded today can be the other
end of a relation stated earlier. Writes an edge only where both dossiers are in the graph.
"""

from __future__ import annotations

from collections import Counter

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    RELATION_ACCOMPANIES,
    RELATION_RELATED_TO,
    RELATION_REVISES,
)
from lawgraph.core.dossier_relations import (
    DossierRef,
    accompanied_notas,
    budget_amendments,
    related_dossiers,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-dossier-relations"


class TKDossierRelationsSemanticPipeline(SemanticPipelineBase):
    """Write ``RELATED_TO``, ``REVISES`` and ``ACCOMPANIES`` between dossiers."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        dossiers = [
            DossierRef.of(row)
            for row in self._track(
                semantic_queries.dossier_refs(self.store), "dossiers"
            )
        ]
        keys = {make_node_key(dossier.label) for dossier in dossiers}
        cases = self._track(semantic_queries.related_cases(self.store), "related cases")
        found = (
            (RELATION_RELATED_TO, related_dossiers(cases)),
            (RELATION_REVISES, budget_amendments(dossiers)),
            (RELATION_ACCOMPANIES, accompanied_notas(dossiers)),
        )

        written: Counter[str] = Counter()
        edges = EdgeWriter(self.store, what=None)
        for relation, links in found:
            for link in links:
                from_key = make_node_key(link.from_label)
                to_key = make_node_key(link.to_label)
                if from_key in keys and to_key in keys and from_key != to_key:
                    edges.add(
                        f"{COLLECTION_DOSSIERS}/{from_key}",
                        f"{COLLECTION_DOSSIERS}/{to_key}",
                        relation,
                        source=SEMANTIC_SOURCE,
                        meta=link.meta,
                    )
                    written[relation] += 1
        edges.flush_into(result)
        logger.info(
            "Dossier relations: %s.",
            ", ".join(f"{written[r]} {r}" for r, _ in found),
        )
        return result
