"""``semantic verdragenbank``: what the register of a treaty names, as edges.

From each Verdragenbank treaty (``verdrag_<id>``, its props from the item XML, see
``core.verdragenbank_xml``):

* ``PUBLISHED_IN`` to each Tractatenblad it lists (``trb_<year>_<number>``, ``meta.description``
  as the register writes it). A Tractatenblad that is not in the graph yet becomes an
  instrument of kind ``publicatie`` with what the register says of it; one that is (from the
  BWB) is left as it is;
* ``LEGISLATED_IN`` to the dossier of its approval, for a dossier that is in the graph: the
  number is the leading digits of the register's ``DossierNummer`` ("8689 (R542)" is 8689);
* ``PART_OF`` to the treaty it belongs to (``Moederverdrag``: a Protocol to its Convention),
  when that treaty is in the graph.

Derived in full on every run: an edge the register no longer names goes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    EDGE_SOURCE_VERDRAGENBANK,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_PUBLISHED_IN,
)
from lawgraph.core.bwb_xml import KIND_PUBLICATION, publication_key
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter, NodeWriter, edge_key
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import verdragenbank as semantic_verdragenbank

from .base import SemanticPipelineBase

logger = get_logger(__name__)

_RELATIONS = (RELATION_PUBLISHED_IN, RELATION_LEGISLATED_IN, RELATION_PART_OF)
_TRB_ID = re.compile(r"^trb-(\d{4})-(\d+)$")
_DOSSIER_NUMBER = re.compile(r"^\s*(\d+)")


def _list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def trb_node(official_id: str) -> Node | None:
    """The instrument of the Tractatenblad ``trb-1951-154``, with what its id says."""
    match = _TRB_ID.match(official_id)
    if not match:
        return None
    year, number = int(match[1]), str(int(match[2]))
    name = f"Trb. {year}, {number}"
    return Node(
        collection=COLLECTION_INSTRUMENTS,
        type=NodeType.INSTRUMENT,
        key=publication_key(official_id),
        labels=["Verdrag", "Publication"],
        props={
            "display_name": name,
            "citation_title": name,
            "kind": KIND_PUBLICATION,
            "jurisdiction": "nl",
            "source": EDGE_SOURCE_VERDRAGENBANK,
            "official_id": official_id,
            "publication_kind": "Trb",
            "publication_year": year,
            "publication_number": number,
        },
    )


def dossier_number(text: Any) -> str | None:
    """The dossier number of the register's ``DossierNummer``: "8689 (R542)" is ``8689``."""
    match = _DOSSIER_NUMBER.match(str(text or ""))
    return match[1] if match else None


class VerdragenbankSemanticPipeline(SemanticPipelineBase):
    """PUBLISHED_IN, LEGISLATED_IN and PART_OF from what the register of a treaty names."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        treaties = list(
            self._track(semantic_verdragenbank.treaty_registers(self.store), "treaties")
        )
        wanted = self._wanted(treaties)
        present = self._present(wanted)
        edges = EdgeWriter(self.store, what=None)
        kept: dict[str, set[str]] = {}
        with NodeWriter(self.store) as nodes:
            for source_id, target_id, relation, meta in wanted:
                if target_id not in present:
                    node = self._new_publication(target_id, relation)
                    if node is None:
                        continue
                    nodes.add(node)
                    present.add(target_id)
                edges.add(
                    source_id,
                    target_id,
                    relation,
                    source=EDGE_SOURCE_VERDRAGENBANK,
                    confidence=1.0,
                    meta=meta,
                )
                kept.setdefault(source_id, set()).add(
                    edge_key(source_id, relation, target_id)
                )
        edges.flush_into(result)
        read = [f"{COLLECTION_INSTRUMENTS}/{t['key']}" for t in treaties]
        removed = sum(
            semantic_edges.remove_edges_from(
                self.store, relation, EDGE_SOURCE_VERDRAGENBANK, read, kept
            )
            for relation in _RELATIONS
        )
        logger.info(
            "%d treaties: %d edges; removed %d the register no longer names.",
            len(treaties),
            sum(len(keys) for keys in kept.values()),
            removed,
        )
        return result

    @staticmethod
    def _wanted(
        treaties: Iterable[dict[str, Any]],
    ) -> list[tuple[str, str, str, dict[str, Any]]]:
        """``(source id, target id, relation, meta)`` of every edge the registers name."""
        wanted: dict[tuple[str, str, str], dict[str, Any]] = {}
        for treaty in treaties:
            source = f"{COLLECTION_INSTRUMENTS}/{treaty['key']}"
            for trb in _list(treaty.get("tractatenblad")):
                official_id = str(trb.get("official_id") or "")
                if _TRB_ID.match(official_id):
                    target = f"{COLLECTION_INSTRUMENTS}/{publication_key(official_id)}"
                    meta = {"tractatenblad": trb.get("text")}
                    if trb.get("description"):
                        meta["description"] = trb["description"]
                    wanted.setdefault((source, target, RELATION_PUBLISHED_IN), meta)
            for paper in _list(treaty.get("kamerstukken")):
                number = dossier_number(paper.get("dossier"))
                if number:
                    target = f"{COLLECTION_DOSSIERS}/{make_node_key(number)}"
                    meta = {"dossier_number": number}
                    if paper.get("rijks_number"):
                        meta["rijks_number"] = paper["rijks_number"]
                    wanted.setdefault((source, target, RELATION_LEGISLATED_IN), meta)
            for parent in _list(treaty.get("parent_treaties")):
                if parent.get("id"):
                    key = make_node_key("verdrag", str(parent["id"]))
                    target = f"{COLLECTION_INSTRUMENTS}/{key}"
                    if target != source:
                        meta = {"verdrag_id": str(parent["id"])}
                        wanted.setdefault((source, target, RELATION_PART_OF), meta)
        return [(s, t, r, meta) for (s, t, r), meta in wanted.items()]

    def _present(self, wanted: list[tuple[str, str, str, dict[str, Any]]]) -> set[str]:
        """The ids among the targets of *wanted* that are in the graph: one check per
        collection."""
        present: set[str] = set()
        for collection in (COLLECTION_INSTRUMENTS, COLLECTION_DOSSIERS):
            keys = {
                t.split("/", 1)[1]
                for _, t, _, _ in wanted
                if t.startswith(collection + "/")
            }
            if keys:
                present |= {
                    f"{collection}/{key}"
                    for key in self.store.existing_keys(collection, keys)
                }
        return present

    @staticmethod
    def _new_publication(target_id: str, relation: str) -> Node | None:
        """The node of a Tractatenblad that is not in the graph yet; None for any other
        target that is missing (a dossier or a treaty: no edge)."""
        if relation != RELATION_PUBLISHED_IN:
            return None
        key = target_id.split("/", 1)[1]
        match = re.fullmatch(r"trb_(\d{4})_(\d+)", key)
        return trb_node(f"trb-{match[1]}-{match[2]}") if match else None
