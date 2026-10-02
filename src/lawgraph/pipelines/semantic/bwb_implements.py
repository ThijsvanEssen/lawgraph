"""``semantic bwb-implements``: which Dutch law implements which EU act, and which only
names one.

IMPLEMENTS to an EU act in the graph rests on an implementation source, never on a mention
alone; ``meta.bases`` says which:

* ``national_implementing_measure``: EUR-Lex lists the publication as a Dutch measure
  implementing the act (``retrieve eurlex-nim``). The edge goes from the publication (when
  the graph has it) and from every regulation it enacted or made an article version of;
  ``meta.publications`` names the measures, ``meta.measures`` each with how it is cited and its
  title and kind of act as EUR-Lex gives them (the law that changed the Awb to implement it).
  Not from articles: a measure names no article,
  and what it changed may be more than the implementation (a republication of a code, a
  law amending several others);
* ``considerans``: the considerans of the regulation says it implements the act ("ter
  uitvoering van", "te implementeren", the "Gelet op" of an order), as ``normalize bwb``
  keeps it (``props.implements_celex``).

An EU act a regulation's text names by CELEX number (``props.celex_refs``) that it does not
implement is a REFERS_TO from the regulation. Both relations are derived in full on every
run: an edge no longer derived goes.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    EDGE_SOURCE_BWB_IMPLEMENTS,
    IMPLEMENTS_BASIS_CONSIDERANS,
    IMPLEMENTS_BASIS_NIM,
    RELATION_IMPLEMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.bwb_xml import publication_key
from lawgraph.core.eurlex_nim import measure_publication, measure_summary
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.db import EdgeWriter, edge_key
from lawgraph.db.queries.normalize import edges as normalize_edges
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import eu as semantic_eu

from .base import SemanticPipelineBase

logger = get_logger(__name__)


def _regulation_id(bwb_id: str) -> str:
    return f"{COLLECTION_INSTRUMENTS}/{make_node_key(bwb_id)}"


def _act_key(celex: str) -> str:
    return make_node_key(celex)


@dataclass
class _Link:
    """What one IMPLEMENTS edge rests on."""

    celex: str
    bases: set[str] = field(default_factory=set)
    publications: set[str] = field(default_factory=set)
    measures: dict[str, dict[str, Any]] = field(default_factory=dict)  # by publication

    def meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {"celex": self.celex, "bases": sorted(self.bases)}
        if self.publications:
            meta["publications"] = sorted(self.publications)
        if self.measures:
            meta["measures"] = [self.measures[p] for p in sorted(self.measures)]
        return meta


class BWBImplementsSemanticPipeline(SemanticPipelineBase):
    """IMPLEMENTS from an implementation source; REFERS_TO for the other EU acts named."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        links: dict[tuple[str, str], _Link] = {}
        named: dict[str, set[str]] = defaultdict(set)  # regulation id -> CELEX named

        for row in self._track(
            semantic_eu.eu_references(self.store), "regulations naming EU acts"
        ):
            regulation = _regulation_id(str(row["bwb_id"]))
            named[regulation].update(row.get("named") or [])
            for celex in row.get("implements") or []:
                self._link(links, regulation, celex, IMPLEMENTS_BASIS_CONSIDERANS)
        self._link_measures(links)

        acts = self._acts_in_graph(
            {link.celex for link in links.values()}
            | {celex for celexes in named.values() for celex in celexes}
        )
        implemented = self._write_implements(links, acts, result)
        self._write_mentions(named, implemented, acts, result)
        return result

    @staticmethod
    def _link(
        links: dict[tuple[str, str], _Link],
        source_id: str,
        celex: str,
        basis: str,
        publication: str | None = None,
        measure: dict[str, Any] | None = None,
    ) -> None:
        link = links.setdefault((source_id, celex), _Link(celex))
        link.bases.add(basis)
        if publication:
            link.publications.add(publication)
        if publication and measure:
            link.measures.setdefault(publication, measure)

    # ------------------------------------------------------------------ EUR-Lex

    def _link_measures(self, links: dict[tuple[str, str], _Link]) -> None:
        """IMPLEMENTS from each measure's publication and from the regulations it enacted
        or changed."""
        acts_of: dict[str, set[str]] = defaultdict(set)  # publication id -> CELEX
        summary_of: dict[
            str, dict[str, Any]
        ] = {}  # publication id -> its first measure
        measures = unresolved = 0
        for measure in semantic_eu.national_measures(self.store):
            measures += 1
            publication = measure_publication(measure)
            if publication is None:
                unresolved += 1
                continue
            acts_of[publication].update(measure.get("celex") or [])
            summary_of.setdefault(publication, measure_summary(measure, publication))
        logger.info(
            "%d national implementing measures: %d publications, %d name none.",
            measures,
            len(acts_of),
            unresolved,
        )
        if not acts_of:
            return
        present = self.store.existing_keys(
            COLLECTION_INSTRUMENTS, {publication_key(p) for p in acts_of}
        )
        for publication, celexes in acts_of.items():
            if publication_key(publication) in present:
                source_id = f"{COLLECTION_INSTRUMENTS}/{publication_key(publication)}"
                for celex in celexes:
                    self._link(
                        links,
                        source_id,
                        celex,
                        IMPLEMENTS_BASIS_NIM,
                        publication,
                        summary_of[publication],
                    )
        for publication, bwb_id in semantic_eu.regulations_of_publications(
            self.store, sorted(acts_of)
        ):
            for celex in acts_of[publication]:
                self._link(
                    links,
                    _regulation_id(bwb_id),
                    celex,
                    IMPLEMENTS_BASIS_NIM,
                    publication,
                    summary_of[publication],
                )

    # ------------------------------------------------------------------ writing

    def _acts_in_graph(self, celexes: Iterable[str]) -> set[str]:
        """The CELEX numbers of *celexes* whose EU act is in the graph."""
        by_key = {_act_key(celex): celex for celex in celexes}
        present = self.store.existing_keys(COLLECTION_INSTRUMENTS, set(by_key))
        return {by_key[key] for key in present}

    def _write_implements(
        self,
        links: dict[tuple[str, str], _Link],
        acts: set[str],
        result: PipelineResult,
    ) -> set[tuple[str, str]]:
        """Write IMPLEMENTS to the acts in the graph; ``(source id, CELEX)`` written."""
        keep: list[str] = []
        written: set[tuple[str, str]] = set()
        with EdgeWriter(self.store, what=None) as edges:
            for (source_id, celex), link in sorted(links.items()):
                target_id = f"{COLLECTION_INSTRUMENTS}/{_act_key(celex)}"
                if celex not in acts or source_id == target_id:
                    continue
                edges.add(
                    source_id,
                    target_id,
                    RELATION_IMPLEMENTS,
                    source=EDGE_SOURCE_BWB_IMPLEMENTS,
                    confidence=1.0,
                    meta=link.meta(),
                )
                keep.append(edge_key(source_id, RELATION_IMPLEMENTS, target_id))
                written.add((source_id, celex))
        edges.flush_into(result)
        # the only writer of IMPLEMENTS: every edge it no longer derives goes
        removed = normalize_edges.remove_edges_except(
            self.store, RELATION_IMPLEMENTS, keep
        )
        logger.info("IMPLEMENTS: %d edges, %d no longer derived.", len(keep), removed)
        return written

    def _write_mentions(
        self,
        named: dict[str, set[str]],
        implemented: set[tuple[str, str]],
        acts: set[str],
        result: PipelineResult,
    ) -> None:
        """REFERS_TO from a regulation to the EU acts its text names and it does not
        implement."""
        keep: list[str] = []
        with EdgeWriter(self.store, what=None) as edges:
            for source_id, celexes in sorted(named.items()):
                for celex in sorted(celexes):
                    target_id = f"{COLLECTION_INSTRUMENTS}/{_act_key(celex)}"
                    if celex not in acts or (source_id, celex) in implemented:
                        continue
                    if source_id == target_id:
                        continue
                    edges.add(
                        source_id,
                        target_id,
                        RELATION_REFERS_TO,
                        source=EDGE_SOURCE_BWB_IMPLEMENTS,
                        confidence=1.0,
                        meta={"celex": celex},
                    )
                    keep.append(edge_key(source_id, RELATION_REFERS_TO, target_id))
        edges.flush_into(result)
        removed = semantic_edges.remove_edges_of_source_except(
            self.store, RELATION_REFERS_TO, EDGE_SOURCE_BWB_IMPLEMENTS, keep
        )
        logger.info(
            "REFERS_TO an EU act: %d edges, %d no longer derived.", len(keep), removed
        )
