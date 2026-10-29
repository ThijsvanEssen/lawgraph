"""Semantic pipeline: BWB regulation → BASED_ON → the article it is issued under.

The BWB XML states the legal basis in the preamble: the paragraph that starts with
"Gelet op" contains ``<extref bwb-id=… doc="jci1.3:c:BWBR0001947&artikel=125">``
elements. ``normalize bwb`` reads them (``core.bwb_xml.parse_toestand``) and keeps them on
the regulation as ``props.basis``; this pipeline turns each entry that names an article into

    Instrument(regulation) --BASED_ON--> Article(basis regulation, article)

with ``meta = {text, basis_kind}``: the reference without its list word and law ("16,
eerste en zevende lid") and whether the article gives the power the regulation is made under
(``delegates``) or is only named (``mentioned``, ``core.delegations.basis_kind``).
A law the preamble names without a link ("artikelen 1, 2 en 4 van de
Arbeidsomstandighedenwet", the law only in words) is read from the text of the "Gelet op"
paragraphs (``props.basis_preamble``) by the citation extractor, by the name of the law as the
graph knows it; a name it does not know, or that two laws share, names nothing. Such an edge
has the confidence of the citation, and stands only for an article the links do not name.
The text is dated by the regulation: it names no law that came to be after it. A reference in
words of a regulation older than the first toestand the BWB holds of its law (most from 2002
on), to a number that toestand has no article of, names no article: that number was another
article then, or none. It is kept as a gap on the regulation, ``props.basis_unresolved``,
written when it changed. A number the first toestand has is linked: no source says whether it
was the same article before (the Grondwet was renumbered in 1983, "gelet op artikel 86 der
Grondwet" of 1959 is not the article 86 of now, and the BWB holds it from 2002).
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
from lawgraph.core.citations import DutchCitationExtractor, LawDates
from lawgraph.core.delegations import (
    basis_kind,
    basis_qualifier,
    basis_range_end,
    basis_text,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb

from ._detection import build_extractor
from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "bwb-grondslagen-linker"

_CHUNK = 500

# Why a reference of a preamble names no article (``props.basis_unresolved``): the regulation
# is older than the first toestand the BWB holds of the law it names, which has no article of
# that number.
UNRESOLVED_NOT_IN_FIRST_VERSION = "not_in_first_version"

# (regulation key, basis BWB id, the "Gelet op" reference, its confidence)
_Ref = tuple[str, str, dict[str, Any], float]


class BWBGrondslagenSemanticPipeline(SemanticPipelineBase):
    """Create BASED_ON edges from BWB regulations to their legal-basis articles."""

    _extractor: DutchCitationExtractor | None = None
    _law_dates: dict[str, LawDates] | None = None

    def _dates(self) -> dict[str, LawDates]:
        """The dates of the laws (``_load_law_dates``), read once."""
        if self._law_dates is None:
            self._law_dates = self._load_law_dates()
        return self._law_dates

    def run(self) -> PipelineResult:
        result = PipelineResult()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        rows = semantic_bwb.regulations_with_basis(self.store)
        with NodeWriter(self.store) as nodes:
            for chunk in chunked(self._track(rows, "regulations with a basis"), _CHUNK):
                self._link_chunk(chunk, edges, nodes, result)
        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_BASED_ON, EDGE_SOURCE)
        logger.info("Legal bases: %d edges no basis states any more removed.", removed)
        return result

    def _link_chunk(
        self,
        rows: list[dict[str, Any]],
        edges: EdgeWriter,
        nodes: NodeWriter,
        result: PipelineResult,
    ) -> None:
        refs: list[_Ref] = []
        worded: dict[str, list[_Ref]] = {}
        for row in rows:
            linked, words = self._basis_refs(row), self._preamble_refs(row)
            if not linked and not words:
                result.skipped += 1
            refs.extend(linked)
            worded[row["key"]] = words
        gaps = self._not_in_first_version(rows, worded)
        for key, words in worded.items():
            refs.extend(ref for ref in words if ref not in gaps.get(key, []))
        for row in rows:
            self._keep_gaps(row, gaps.get(row["key"], []), nodes, result)
        if refs:
            self._link_refs(refs, edges, result)

    def _not_in_first_version(
        self, rows: list[dict[str, Any]], worded: dict[str, list[_Ref]]
    ) -> dict[str, list[_Ref]]:
        """Per regulation the references in its words to a law that the BWB holds no
        toestand of on its date, to a number the first toestand it holds has no article of:
        that number was another article then, or none. A regulation without a date, a law
        whose toestanden are not all dated or whose first toestand has no articles in the
        graph, names no such gap."""
        laws = sorted({law for words in worded.values() for _, law, _, _ in words})
        if not laws:
            return {}
        first = {
            str(row["bwb_id"]).upper(): (
                str(row["first_from"])[:10],
                set(row["numbers"]),
            )
            for row in semantic_bwb.first_versions(self.store, laws)
            if row["first_from"] and row["numbers"]
        }
        gaps: dict[str, list[_Ref]] = {}
        for row in rows:
            start = self._start(row)
            for ref in worded.get(row["key"], []):
                since, numbers = first.get(ref[1], ("", set()))
                if start and start < since and ref[2]["article"] not in numbers:
                    gaps.setdefault(row["key"], []).append(ref)
        return gaps

    def _start(self, row: dict[str, Any]) -> str | None:
        """When the regulation of *row* came to be (``LawDates.start``), None undated."""
        dated = self._dates().get(str(row.get("bwb_id") or "").upper())
        return dated.start if dated else None

    @staticmethod
    def _keep_gaps(
        row: dict[str, Any], gaps: list[_Ref], nodes: NodeWriter, result: PipelineResult
    ) -> None:
        """Write ``props.basis_unresolved`` of the regulation of *row* when it changed:
        ``{bwb_id, article, text, reason}`` of each reference *gaps* holds, null without
        one."""
        named = dict.fromkeys(
            (ref["bwb_id"], ref["article"], ref["text"]) for _, _, ref, _ in gaps
        )
        kept = [
            {
                "bwb_id": bwb_id,
                "article": article,
                "text": text,
                "reason": UNRESOLVED_NOT_IN_FIRST_VERSION,
            }
            for bwb_id, article, text in named
        ] or None
        if kept == row.get("basis_unresolved"):
            return
        nodes.add(
            Node(
                collection=COLLECTION_INSTRUMENTS,
                key=row["key"],
                props={"basis_unresolved": kept},
            )
        )
        result.updated += 1

    def _link_refs(
        self, refs: list[_Ref], edges: EdgeWriter, result: PipelineResult
    ) -> None:
        """An edge per article *refs* name that is in the graph."""
        order = self._law_order(refs)
        # per (regulation, article) the reference that names it: one of its own before a
        # range it falls in
        links: dict[tuple[str, str], tuple[dict[str, Any], bool]] = {}
        confidence: dict[tuple[str, str], float] = {}
        for source, basis_id, ref, certainty in refs:
            first = make_node_key(basis_id, ref["article"])
            for target in self._range(order, basis_id, first, ref):
                in_range = target != first
                if not in_range or (source, target) not in links:
                    links[(source, target)] = (ref, in_range)
                    confidence[(source, target)] = certainty

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
                confidence=confidence[(source, target)],
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
                for _, basis_id, ref, _ in refs
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

    def _preamble_refs(self, row: dict[str, Any]) -> list[_Ref]:
        """The articles the "Gelet op" text of one regulation names of another law and the
        links do not: ``{bwb_id, article, text}`` per article, the text its leden as written."""
        preamble = str(row.get("basis_preamble") or "")
        if not preamble:
            return []
        if self._extractor is None:
            codes, shared = self._load_code_choices()
            self._extractor = build_extractor(
                codes,
                self._load_instrument_aliases(),
                None,
                self._dates(),
                shared,
            )
        bwb_id = str(row.get("bwb_id") or "").upper()
        linked = {
            (str(ref.get("bwb_id") or "").upper(), ref.get("article"))
            for ref in row.get("basis") or []
        }
        refs: list[_Ref] = []
        for hit in self._extractor.extract(
            preamble, every_occurrence=True, chains=True, on=self._start(row)
        ):
            law = (hit.bwb_id or "").upper()
            if not law or law == bwb_id or (law, hit.article_number) in linked:
                continue
            text = ", ".join(filter(None, (hit.article_number, hit.qualifier)))
            refs.append(
                (
                    row["key"],
                    law,
                    {"bwb_id": law, "article": hit.article_number, "text": text},
                    hit.confidence,
                )
            )
        return refs

    @staticmethod
    def _basis_refs(row: dict[str, Any]) -> list[_Ref]:
        """The basis entries of one regulation that name an article of another."""
        bwb_id = str(row.get("bwb_id") or "").upper()
        refs: list[_Ref] = []
        for ref in row.get("basis") or []:
            basis_id = str(ref.get("bwb_id") or "").upper()
            if not ref.get("article") or not basis_id or basis_id == bwb_id:
                continue  # no target article, or a reference to itself
            refs.append((row["key"], basis_id, ref, EXACT_CONFIDENCE))
        return refs
