"""Write the relations between dossiers of different numbers, and between cases and between
activities, from the graph.

``RELATED_TO`` is the Kamer's own relation between two cases (``Zaak.GerelateerdNaar``,
stored on the case by ``normalize tk``) lifted to their dossiers; ``REVISES`` and
``ACCOMPANIES`` follow from the titles of the budget laws; ``SECOND_READING_OF`` from the
memorandum of a second reading of a change in the Grondwet, which refers to the first. The rules are
:mod:`lawgraph.core.dossier_relations`.

The same Kamer relation also ties the two cases themselves (``RELATED_TO`` case → case, also
within one dossier or without one: a letter of the government and the motion it answers), and a
moved activity is ``CONTINUES``d by the one that replaced it (``Activiteit.VervangenDoor``;
``meta.reason`` ``verplaatst``). A paper of a case that replaces another (an amended amendment
or motion, ``Zaak.VervangenVanuit``) ``REVISES`` the papers of that case (``meta.rule``
``vervanging``).

Runs over every dossier, every related case and every activity, since a node loaded today can be
the other end of a relation stated earlier. Writes an edge only where both ends are in the graph.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOSSIERS,
    RELATION_ACCOMPANIES,
    RELATION_CONTINUES,
    RELATION_RELATED_TO,
    RELATION_REVISES,
    RELATION_SECOND_READING_OF,
)
from lawgraph.core.dossier_relations import (
    DossierRef,
    accompanied_notas,
    budget_amendments,
    first_readings,
    moved_activities,
    related_case_pairs,
    related_dossiers,
    replaced_cases,
    replaced_papers,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-dossier-relations"


class TKDossierRelationsSemanticPipeline(SemanticPipelineBase):
    """Write ``RELATED_TO``, ``REVISES``, ``ACCOMPANIES`` and ``SECOND_READING_OF``."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        dossiers = [
            DossierRef.of(row)
            for row in self._track(semantic_tk.dossier_refs(self.store), "dossiers")
        ]
        keys = {make_node_key(dossier.label) for dossier in dossiers}
        cases = list(
            self._track(semantic_tk.related_cases(self.store), "related cases")
        )
        found = (
            (RELATION_RELATED_TO, related_dossiers(cases)),
            (RELATION_REVISES, budget_amendments(dossiers)),
            (RELATION_ACCOMPANIES, accompanied_notas(dossiers)),
            (
                RELATION_SECOND_READING_OF,
                first_readings(semantic_tk.second_reading_memoranda(self.store)),
            ),
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
        written["RELATED_TO between cases"] = self._relate_cases(cases, edges)
        written["moved activities"] = self._continue_moved(edges)
        written["replaced papers"] = self._revise_replaced(edges)
        edges.flush_into(result)
        logger.info(
            "Dossier relations: %s.",
            ", ".join(f"{count} {what}" for what, count in written.items()),
        )
        return result

    def _relate_cases(self, cases: list[dict[str, Any]], edges: EdgeWriter) -> int:
        """``RELATED_TO`` between the two cases of each relation, both stored."""
        pairs = list(related_case_pairs(cases))
        stored = self.store.existing_keys(
            COLLECTION_CASES, {make_node_key(i) for pair in pairs for i in pair[:2]}
        )
        count = 0
        for case, other, meta in pairs:
            from_key, to_key = make_node_key(case), make_node_key(other)
            if from_key in stored and to_key in stored:
                edges.add(
                    f"{COLLECTION_CASES}/{from_key}",
                    f"{COLLECTION_CASES}/{to_key}",
                    RELATION_RELATED_TO,
                    source=SEMANTIC_SOURCE,
                    meta=meta,
                )
                count += 1
        return count

    def _revise_replaced(self, edges: EdgeWriter) -> int:
        """``REVISES`` from each paper of a case to each paper of the case it replaces
        (``Zaak.VervangenVanuit``: "Gewijzigd amendement ter vervanging van nr. 21")."""
        cases = replaced_cases(semantic_tk.replacing_cases(self.store))
        papers = semantic_tk.papers_of_cases(
            self.store, sorted({case for pair in cases for case in pair})
        )
        count = 0
        for paper, replaced in replaced_papers(cases, papers):
            edges.add(
                paper,
                replaced,
                RELATION_REVISES,
                source=SEMANTIC_SOURCE,
                meta={"rule": "vervanging"},
            )
            count += 1
        return count

    def _continue_moved(self, edges: EdgeWriter) -> int:
        """``CONTINUES`` from the activity that replaced a moved one to it."""
        count = 0
        for replacing, moved in moved_activities(
            semantic_tk.activity_numbers(self.store)
        ):
            edges.add(
                replacing,
                moved,
                RELATION_CONTINUES,
                source=SEMANTIC_SOURCE,
                meta={"reason": "verplaatst"},
            )
            count += 1
        return count
