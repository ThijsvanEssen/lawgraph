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
``meta.reason`` ``verplaatst``). A document of a case that replaces another (an amended amendment
or motion, ``Zaak.VervangenVanuit``) ``REVISES`` the documents of that case (``meta.rule``
``vervanging``). A motion is ``MADE_IN`` the debate it was submitted in: the debate held on
the day its case started that has the case on its agenda and took no decision on it
(``meta.reason`` ``ingediend``).

Runs over every dossier, every related case and every activity, since a node loaded today can be
the other end of a relation stated earlier. Writes an edge only where both ends are in the graph.
Derived in full on every run: an edge of these relations no rule gives any more goes.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOSSIERS,
    RELATION_ACCOMPANIES,
    RELATION_CONTINUES,
    RELATION_MADE_IN,
    RELATION_RELATED_TO,
    RELATION_REVISES,
    RELATION_SECOND_READING_OF,
)
from lawgraph.core.dossier_relations import (
    RULE_REPLACEMENT,
    DossierRef,
    accompanied_notas,
    budget_amendments,
    first_readings,
    moved_activities,
    related_case_ids,
    related_case_pairs,
    related_dossiers,
    replaced_cases,
    replaced_documents,
)
from lawgraph.core.dossier_stages import ACTIVITY_HELD
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key, node_id
from lawgraph.core.provenance import REASON_MOVED, REASON_SUBMITTED
from lawgraph.core.tk_records.kinds import KIND_MOTION
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.sources.addresses import edge_source

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
RELATIONS = (
    RELATION_RELATED_TO,
    RELATION_REVISES,
    RELATION_ACCOMPANIES,
    RELATION_SECOND_READING_OF,
    RELATION_CONTINUES,
    RELATION_MADE_IN,
)


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
        documents = semantic_tk.case_documents(self.store, related_case_ids(cases))
        found = (
            (RELATION_RELATED_TO, related_dossiers(cases, documents)),
            (RELATION_REVISES, budget_amendments(dossiers)),
            (RELATION_ACCOMPANIES, accompanied_notas(dossiers)),
            (
                RELATION_SECOND_READING_OF,
                first_readings(semantic_tk.second_reading_memoranda(self.store)),
            ),
        )

        written: Counter[str] = Counter()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for relation, links in found:
            for link in links:
                from_key = make_node_key(link.from_label)
                to_key = make_node_key(link.to_label)
                if from_key in keys and to_key in keys and from_key != to_key:
                    edges.add(
                        node_id(COLLECTION_DOSSIERS, from_key),
                        node_id(COLLECTION_DOSSIERS, to_key),
                        relation,
                        source=EDGE_SOURCE,
                        meta=link.meta,
                    )
                    written[relation] += 1
        written["RELATED_TO between cases"] = self._relate_cases(cases, edges)
        written["moved activities"] = self._continue_moved(edges)
        written["replaced papers"] = self._revise_replaced(edges)
        written["motions submitted in a debate"] = self._motions_made_in(edges)
        edges.flush_into(result)
        written["removed"] = sum(
            edges.remove_stale_of_source(relation, EDGE_SOURCE)
            for relation in RELATIONS
        )
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
                    node_id(COLLECTION_CASES, from_key),
                    node_id(COLLECTION_CASES, to_key),
                    RELATION_RELATED_TO,
                    source=EDGE_SOURCE,
                    meta=meta,
                )
                count += 1
        return count

    def _revise_replaced(self, edges: EdgeWriter) -> int:
        """``REVISES`` from each document of a case to each document of the case it replaces
        (``Zaak.VervangenVanuit``: "Gewijzigd amendement ter vervanging van nr. 21")."""
        cases = replaced_cases(semantic_tk.replacing_cases(self.store))
        documents = semantic_tk.documents_of_cases(
            self.store, sorted({case for pair in cases for case in pair})
        )
        count = 0
        for document, replaced in replaced_documents(cases, documents):
            edges.add(
                document,
                replaced,
                RELATION_REVISES,
                source=EDGE_SOURCE,
                meta={"rule": RULE_REPLACEMENT},
            )
            count += 1
        return count

    def _motions_made_in(self, edges: EdgeWriter) -> int:
        """``MADE_IN`` from each motion to the debate it was submitted in
        (``semantic_tk.motions_submitted``; ``meta.reason`` ``ingediend``); how many."""
        count = 0
        for row in semantic_tk.motions_submitted(
            self.store, KIND_MOTION, ACTIVITY_HELD
        ):
            edges.add(
                row["paper"],
                row["activity"],
                RELATION_MADE_IN,
                source=EDGE_SOURCE,
                meta={"reason": REASON_SUBMITTED},
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
                source=EDGE_SOURCE,
                meta={"reason": REASON_MOVED},
            )
            count += 1
        return count
