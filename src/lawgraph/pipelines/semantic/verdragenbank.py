"""``semantic verdragenbank``: what the register of a treaty names, as edges.

From each Verdragenbank treaty (``verdrag_<id>``, its props from the item XML, see
``core.verdragenbank_xml``):

* ``PUBLISHED_IN`` to each Tractatenblad it lists (``trb_<year>_<number>``, ``meta.description``
  as the register writes it). A Tractatenblad that is not in the graph yet becomes an
  instrument of kind ``publicatie`` with what the register says of it; one that is (from the
  BWB) is left as it is;
* ``LEGISLATED_IN`` to the dossier of its approval, for a dossier that is in the graph: the
  number is the leading digits of the register's ``DossierNummer`` ("8689 (R542)" is 8689),
  which names the dossier of a Rijkswet too (``8689-(R542)``, ``queries/dossier_keys``);
* ``PART_OF`` to the treaty it belongs to (``Moederverdrag``: a Protocol to its Convention),
  when that treaty is in the graph;
* ``SAME_AS`` into it from the BWB text of the treaty (``BWBV…``), which names it by its
  treaty number (``wetgeving@verdragnummer``).

Derived in full on every run: an edge the register no longer names goes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    COLLECTION_INSTRUMENTS,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_PUBLISHED_IN,
    RELATION_SAME_AS,
)
from lawgraph.core.bwb_xml import publication_key, publication_props
from lawgraph.core.logging import get_logger
from lawgraph.core.models import (
    Node,
    PipelineResult,
    key_of,
    make_node_key,
    node_id,
)
from lawgraph.core.publications import parse_koop_id
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.dossier_keys import dossier_keys
from lawgraph.db.queries.semantic import verdragenbank as semantic_verdragenbank
from lawgraph.sources.addresses import edge_source

from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)

# The source of what it derives from the register of a treaty: its edges and the treaty
# publications it adds.
EDGE_SOURCE = edge_source(__name__)

_RELATIONS = (RELATION_PUBLISHED_IN, RELATION_LEGISLATED_IN, RELATION_PART_OF)
_DOSSIER_NUMBER = re.compile(r"^\s*(\d+)")


def _list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def trb_node(official_id: str) -> Node | None:
    """The instrument of the Tractatenblad ``trb-1951-154``, with what its id says."""
    parsed = parse_koop_id(official_id)
    if parsed is None or parsed[0] != "trb":
        return None
    _, year, number = parsed
    props = publication_props(
        {
            "kind": "Trb",
            "year": year,
            "number": str(int(number)),
            "url_identifier": official_id,
        }
    )
    return Node(
        collection=COLLECTION_INSTRUMENTS,
        key=publication_key(official_id),
        labels=["Verdrag", "Publication"],
        props={**props, "source": EDGE_SOURCE},
    )


def dossier_number(text: Any) -> str | None:
    """The dossier number of the register's ``DossierNummer``: "8689 (R542)" is ``8689``."""
    match = _DOSSIER_NUMBER.match(str(text or ""))
    return match[1] if match else None


# ``(source id, target id, relation, meta)`` of an edge a register names.
Edge = tuple[str, str, str, dict[str, Any]]


def _published_in(treaty: dict[str, Any]) -> Iterator[tuple[Node, dict[str, Any]]]:
    """The publication of each Tractatenblad the register lists, with the edge's meta."""
    for trb in _list(treaty.get("tractatenblad")):
        node = trb_node(str(trb.get("official_id") or ""))
        if node is not None:
            description = trb.get("description")
            yield node, {"description": description} if description else {}


def _legislated_in(treaty: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """The dossier number of each Kamerstuk the register lists, with the edge's meta."""
    for document in _list(treaty.get("kamerstukken")):
        number = dossier_number(document.get("dossier"))
        if number:
            yield number, {"dossier_number": number}


def _part_of(treaty: dict[str, Any]) -> Iterator[str]:
    """The treaty each ``Moederverdrag`` names."""
    for parent in _list(treaty.get("parent_treaties")):
        if parent.get("id"):
            yield node_id(
                COLLECTION_INSTRUMENTS, make_node_key("verdrag", str(parent["id"]))
            )


class VerdragenbankSemanticPipeline(SemanticPipelineBase):
    """PUBLISHED_IN, LEGISLATED_IN and PART_OF from what the register of a treaty names, and
    SAME_AS into it from its BWB text."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        treaties = list(
            self._track(semantic_verdragenbank.treaty_registers(self.store), "treaties")
        )
        dossiers = dossier_keys(
            self.store, {n for t in treaties for n, _ in _legislated_in(t)}
        )
        wanted, publications = self._wanted(treaties, dossiers)
        present = self._present(wanted)
        edges = EdgeWriter(self.store, what=None, remembers=True)
        with NodeWriter(self.store) as nodes:
            for source_id, target_id, relation, meta in wanted:
                if target_id not in present:
                    # a missing Tractatenblad becomes a publication; a missing dossier or
                    # treaty gives no edge
                    node = publications.get(target_id)
                    if node is None:
                        continue
                    nodes.add(node)
                    present.add(target_id)
                edges.add(
                    source_id,
                    target_id,
                    relation,
                    source=EDGE_SOURCE,
                    confidence=EXACT_CONFIDENCE,
                    meta=meta,
                )
        read = [node_id(COLLECTION_INSTRUMENTS, t["key"]) for t in treaties]
        self._same_as(edges)
        edges.flush_into(result)
        removed = sum(
            edges.remove_stale(relation, EDGE_SOURCE, read) for relation in _RELATIONS
        ) + edges.remove_stale_to([RELATION_SAME_AS], EDGE_SOURCE, read)
        logger.info(
            "%d treaties: %d edges, %d SAME_AS from their BWB text; removed %d the "
            "register no longer names.",
            len(treaties),
            sum(edges.written(relation) for relation in _RELATIONS),
            edges.written(RELATION_SAME_AS),
            removed,
        )
        return result

    def _same_as(self, edges: EdgeWriter) -> None:
        """Queue SAME_AS from the BWB text of a treaty to its Verdragenbank treaty, by
        treaty number. Derived in full: an edge whose number no longer matches goes."""
        for row in semantic_verdragenbank.same_treaties(self.store):
            text_id, register_id = row["text_id"], row["register_id"]
            edges.add(
                text_id,
                register_id,
                RELATION_SAME_AS,
                source=EDGE_SOURCE,
                confidence=EXACT_CONFIDENCE,
            )

    @staticmethod
    def _wanted(
        treaties: Iterable[dict[str, Any]], dossiers: dict[str, str]
    ) -> tuple[list[Edge], dict[str, Node]]:
        """Every edge the registers name, to the dossiers of *dossiers* (number -> key) the
        graph holds, and the publication node of each Tractatenblad they name, by its id."""
        wanted: dict[tuple[str, str, str], dict[str, Any]] = {}
        publications: dict[str, Node] = {}
        for treaty in treaties:
            source = node_id(COLLECTION_INSTRUMENTS, treaty["key"])
            for node, meta in _published_in(treaty):
                target = node_id(COLLECTION_INSTRUMENTS, str(node.key))
                publications[target] = node
                wanted.setdefault((source, target, RELATION_PUBLISHED_IN), meta)
            for number, meta in _legislated_in(treaty):
                if number in dossiers:
                    target = node_id(COLLECTION_DOSSIERS, dossiers[number])
                    wanted.setdefault((source, target, RELATION_LEGISLATED_IN), meta)
            for target in _part_of(treaty):
                if target != source:
                    wanted.setdefault((source, target, RELATION_PART_OF), {})
        return [(s, t, r, meta) for (s, t, r), meta in wanted.items()], publications

    def _present(self, wanted: list[Edge]) -> set[str]:
        """The ids among the targets of *wanted* that are in the graph: one check per
        collection."""
        present: set[str] = set()
        for collection in (COLLECTION_INSTRUMENTS, COLLECTION_DOSSIERS):
            keys = {
                key_of(t) for _, t, _, _ in wanted if t.startswith(collection + "/")
            }
            if keys:
                present |= {
                    f"{collection}/{key}"
                    for key in self.store.existing_keys(collection, keys)
                }
        return present
