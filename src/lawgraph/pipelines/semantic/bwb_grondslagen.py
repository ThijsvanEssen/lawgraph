"""Semantic pipeline: BWB regulation → BASED_ON → the article it is issued under.

The BWB XML states the legal basis in the preamble: the paragraph that starts with
"Gelet op" contains ``<extref bwb-id=… doc="jci1.3:c:BWBR0001947&artikel=125">``
elements. ``normalize bwb`` reads them (``core.bwb_xml.parse_toestand``) and keeps them on
the regulation as ``props.basis``; this pipeline turns each entry that names an article into

    Instrument(regulation) --BASED_ON--> Article(basis regulation, article)

with ``meta = {text, basis_kind}``: the reference without its list word and law ("16,
eerste en zevende lid") and whether the article gives the power the regulation is made under
(``delegates``) or is only named (``mentioned``, ``core.delegations.basis_kind``).
A link to a range ("artikelen 26 tot en met 30") points at its first article; every article
in force of the range, in the order of the law, gets an edge.

Entries without an article number have no target and are skipped, as are
targets that are not in the graph and references to the regulation itself.

Derived in full on every run: an edge whose basis is no longer stated goes. Only the
regulations that state a basis are read, in chunks: per chunk one read of the target
articles, and one of the order of the laws a range in it spans.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_BASED_ON,
)
from lawgraph.core.batching import chunked
from lawgraph.core.delegations import (
    basis_kind,
    basis_qualifier,
    basis_range_end,
    basis_text,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key, node_id
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb

from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "bwb-grondslagen-linker"

_CHUNK = 500

# (regulation key, basis BWB id, the "Gelet op" reference)
_Ref = tuple[str, str, dict[str, Any]]


class BWBGrondslagenSemanticPipeline(SemanticPipelineBase):
    """Create BASED_ON edges from BWB regulations to their legal-basis articles."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        rows = semantic_bwb.regulations_with_basis(self.store)
        for chunk in chunked(self._track(rows, "regulations with a basis"), _CHUNK):
            self._link_chunk(chunk, edges, result)
        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_BASED_ON, EDGE_SOURCE)
        logger.info("Legal bases: %d edges no basis states any more removed.", removed)
        return result

    def _link_chunk(
        self, rows: list[dict[str, Any]], edges: EdgeWriter, result: PipelineResult
    ) -> None:
        refs: list[_Ref] = []
        for row in rows:
            found = self._basis_refs(row)
            if not found:
                result.skipped += 1
            refs.extend(found)
        if not refs:
            return

        order = self._law_order(refs)
        # per (regulation, article) the reference that names it: one of its own before a
        # range it falls in
        links: dict[tuple[str, str], tuple[dict[str, Any], bool]] = {}
        for source, basis_id, ref in refs:
            first = make_node_key(basis_id, ref["article"])
            for target in self._range(order, basis_id, first, ref):
                in_range = target != first
                if not in_range or (source, target) not in links:
                    links[(source, target)] = (ref, in_range)

        targets = {
            row["key"]: row
            for row in semantic_bwb.basis_targets(
                self.store, sorted({target for _, target in links})
            )
        }
        for (source, target), (ref, in_range) in links.items():
            article = targets.get(target)
            if article is None:
                result.skipped += 1
                continue
            text = basis_text(str(ref.get("text") or ""))
            leden = () if in_range else basis_qualifier(text).leden
            edges.add(
                node_id(COLLECTION_INSTRUMENTS, source),
                node_id(COLLECTION_ARTICLES, target),
                RELATION_BASED_ON,
                source=EDGE_SOURCE,
                confidence=EXACT_CONFIDENCE,
                meta={
                    "text": text,
                    "basis_kind": basis_kind(
                        article.get("text"), article.get("parts"), leden
                    ),
                },
            )

    def _law_order(self, refs: list[_Ref]) -> dict[str, list[str]]:
        """The keys of the articles in force of each law a range of *refs* spans, in the
        order of the law; nothing is read for a chunk without a range."""
        laws = sorted(
            {
                basis_id
                for _, basis_id, ref in refs
                if basis_range_end(str(ref.get("text") or ""), ref["article"])
            }
        )
        order: dict[str, list[str]] = {}
        if laws:
            for row in semantic_bwb.articles_in_order(self.store, laws):
                order.setdefault(str(row["bwb_id"]).upper(), []).append(row["key"])
        return order

    @staticmethod
    def _range(
        order: dict[str, list[str]], basis_id: str, first: str, ref: dict[str, Any]
    ) -> list[str]:
        """The article keys *ref* names: its first article, and with a range every article
        in force up to its last, in the order of the law. A range whose ends are not both in
        force names its first article only."""
        last = basis_range_end(str(ref.get("text") or ""), ref["article"])
        keys = order.get(basis_id, [])
        if last is None or first not in keys:
            return [first]
        end = make_node_key(basis_id, last)
        if end not in keys or keys.index(end) < keys.index(first):
            return [first]
        return keys[keys.index(first) : keys.index(end) + 1]

    @staticmethod
    def _basis_refs(row: dict[str, Any]) -> list[_Ref]:
        """The basis entries of one regulation that name an article of another."""
        bwb_id = str(row.get("bwb_id") or "").upper()
        refs: list[_Ref] = []
        for ref in row.get("basis") or []:
            basis_id = str(ref.get("bwb_id") or "").upper()
            if not ref.get("article") or not basis_id or basis_id == bwb_id:
                continue  # no target article, or a reference to itself
            refs.append((row["key"], basis_id, ref))
        return refs
