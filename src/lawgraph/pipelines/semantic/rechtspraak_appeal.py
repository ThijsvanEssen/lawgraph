"""Semantic pipeline: what the earlier judgments of a case are to a later one.

Rechtspraak XML carries ``dcterms:relation`` (the earlier instances, and with ``psi:aanleg``
latereAanleg the later ones) and ``psi:procedure`` (e.g. "Hoger beroep", "Cassatie",
"Verwijzing na Hoge Raad") in its RDF header; normalize stores them as
``props.related_eclis``, ``props.later_eclis`` and ``props.judgment_metadata.type``. From a
judgment to each earlier instance its metadata names (``core.appeals.earlier_instance_relation``):
``CONTINUES`` to an earlier judgment of the same court in the same case, whatever its
procedure; and from a judgment on appeal, in cassation or after referral ``REFERRED_BY`` to the
ruling of the Hoge Raad that sent the case back, ``APPEAL_OF`` to any other (``meta.basis``
``formal_relation``). A later instance a judgment names makes the same edge from that later
judgment, when it is loaded (``later_instance``): the lower court names its appeal, which
need not name it back.

An appeal whose metadata names none is read for the decision its text says it appeals
(``core.appeals.read_appeal_targets``): ``APPEAL_OF`` to the decision of that date with that
case number (``appeal_text``), else the decision is recorded on the judgment as
``props.unresolved_appeal_targets``. The edges of a judgment are derived in full each run: one
no longer derived goes.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
)
from lawgraph.core.appeals import (
    APPEAL_PROCEDURE,
    APPEAL_TARGET_PARAGRAPHS,
    AppealTarget,
    Instance,
    earlier_instance_relation,
    read_appeal_targets,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.db.store import edge_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "rechtspraak-appeal-linker"
BASIS_FORMAL = "formal_relation"
BASIS_LATER = "later_instance"
BASIS_TEXT = "appeal_text"
CONFIDENCE = {BASIS_FORMAL: 0.95, BASIS_LATER: 0.95, BASIS_TEXT: 0.9}
RELATIONS = (RELATION_APPEAL_OF, RELATION_CONTINUES, RELATION_REFERRED_BY)

# (from id, relation, to ECLI, basis, procedure type)
Link = tuple[str, str, str, str, str]


def _link(from_id: str, later: Instance, earlier: Instance, basis: str) -> list[Link]:
    """The edge from *later* (node *from_id*) to *earlier*, if any: ``CONTINUES`` whatever
    the procedure of *later*, the others only from a judgment on appeal, in cassation or
    after referral (``APPEAL_PROCEDURE``)."""
    relation = earlier_instance_relation(later, earlier)
    procedure = later.procedure or ""
    if relation is None or not (
        relation == RELATION_CONTINUES or APPEAL_PROCEDURE.search(procedure)
    ):
        return []
    return [(from_id, relation, earlier.ecli, basis, procedure)]


class RechtspraakAppealSemanticPipeline(SemanticPipelineBase):
    """Create APPEAL_OF, CONTINUES and REFERRED_BY edges from a judgment to the earlier
    judgments of its case."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = list(
            self._track(
                semantic_rechtspraak.judgments_with_related_eclis(self.store),
                "judgments",
            )
        )
        links = self._formal_links(rows)
        # the judgments whose edges are derived here in full: those read, and the later
        # instances that their earlier ones name
        read = sorted({row["j_id"] for row in rows} | {link[0] for link in links})

        texts = list(
            self._track(
                semantic_rechtspraak.appeals_to_read(
                    self.store,
                    procedure=APPEAL_PROCEDURE.pattern,
                    paragraphs=APPEAL_TARGET_PARAGRAPHS,
                ),
                "appeals without an earlier instance",
            )
        )
        unresolved = self._text_links(texts, links)
        read += [row["j_id"] for row in texts if row["read"]]
        logger.info(
            "Earlier instances: %d links; %d appeals name a decision not loaded.",
            len(links),
            len(unresolved),
        )

        kept = self._write_edges(links, result)
        removed = sum(
            semantic_edges.remove_edges_from(
                self.store, relation, SEMANTIC_SOURCE, read, kept.get(relation, {})
            )
            for relation in RELATIONS
        )
        logger.info("Removed %d edges no longer derived.", removed)
        self._write_targets(texts, unresolved, result)
        return result

    def _formal_links(self, rows: list[dict[str, Any]]) -> list[Link]:
        """The edge to each earlier instance the metadata of *rows* names, and from each
        loaded later instance it names; the latter first, so that where a pair names each
        other the edge keeps the basis of the later judgment's own relation."""
        named = sorted(
            {
                e.upper()
                for row in rows
                for e in [*row["related_eclis"], *row["later_eclis"]]
            }
        )
        found = list(semantic_rechtspraak.judgment_instances(self.store, named))
        known = {instance.ecli: instance for instance in map(Instance.of, found)}
        ids = {str(row["ecli"]).upper(): row["id"] for row in found}
        later_links: list[Link] = []
        links: list[Link] = []
        for row in rows:
            this = replace(Instance.of(row), procedure=row.get("procedure_type"))
            for ecli in row["later_eclis"]:
                later = known.get(ecli.upper())
                if later is not None and later.ecli in ids:
                    later_links += _link(ids[later.ecli], later, this, BASIS_LATER)
            for ecli in row["related_eclis"]:
                earlier = known.get(ecli.upper()) or Instance(ecli=ecli.upper())
                links += _link(row["j_id"], this, earlier, BASIS_FORMAL)
        return later_links + links

    def _text_links(
        self, texts: list[dict[str, Any]], links: list[Link]
    ) -> dict[str, list[AppealTarget]]:
        """Add to *links* the decisions the text of an appeal names that are loaded; the
        others per judgment key."""
        named = {
            row["key"]: read_appeal_targets(row["paragraphs"])
            for row in texts
            if row["read"]
        }
        dates = sorted(
            {t.date for targets in named.values() for t in targets if t.case_number}
        )
        on_date: dict[str, list[dict[str, Any]]] = {}
        for candidate in semantic_rechtspraak.decisions_on_dates(self.store, dates):
            on_date.setdefault(candidate["date"], []).append(candidate)
        by_key = {row["key"]: row for row in texts}
        unresolved: dict[str, list[AppealTarget]] = {}
        for key, targets in named.items():
            row = by_key[key]
            for target in targets:
                found = sorted(
                    {
                        c["ecli"].upper()
                        for c in on_date.get(target.date, [])
                        if target.is_decision(c) and c["ecli"].upper() != row["ecli"]
                    }
                )
                links += [
                    (row["j_id"], RELATION_APPEAL_OF, ecli, BASIS_TEXT, "")
                    for ecli in found
                ]
                if not found:
                    unresolved.setdefault(key, []).append(target)
        return unresolved

    def _write_edges(
        self, links: list[Link], result: PipelineResult
    ) -> dict[str, dict[str, set[str]]]:
        """Write the edges; the keys of those written, per relation and judgment."""
        ids = self._resolve_eclis({link[2] for link in links})
        kept: dict[str, dict[str, set[str]]] = {}
        edges = EdgeWriter(self.store, what=None)
        for from_id, relation, ecli, basis, procedure_type in links:
            to_id = ids.get(ecli)
            if not to_id:
                continue
            meta: dict[str, Any] = {"basis": basis}
            if procedure_type:
                meta["procedure_type"] = procedure_type
            edges.add(
                from_id,
                to_id,
                relation,
                source=SEMANTIC_SOURCE,
                confidence=CONFIDENCE[basis],
                meta=meta,
            )
            kept.setdefault(relation, {}).setdefault(from_id, set()).add(
                edge_key(from_id, relation, to_id)
            )
        edges.flush_into(result)
        return kept

    def _write_targets(
        self,
        texts: list[dict[str, Any]],
        unresolved: dict[str, list[AppealTarget]],
        result: PipelineResult,
    ) -> None:
        """``props.unresolved_appeal_targets`` of each judgment, null when it has none;
        only those that change are written."""
        with NodeWriter(self.store) as writer:
            for row in texts:
                targets = [t.as_props() for t in unresolved.get(row["key"], [])] or None
                if targets == row.get("unresolved_appeal_targets"):
                    continue
                writer.add(
                    Node(
                        collection=COLLECTION_JUDGMENTS,
                        type=NodeType.JUDGMENT,
                        key=row["key"],
                        props={"unresolved_appeal_targets": targets},
                    )
                )
                result.updated += 1
