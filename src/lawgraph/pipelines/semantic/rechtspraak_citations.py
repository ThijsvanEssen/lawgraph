"""``REFERS_TO`` between judgments: the ECLIs a judgment names in its text.

Only the text the court or advocate-general wrote is read (``core.judgments.body_text``), never
the metadata: its ``dcterms:relation`` names the earlier instance and the conclusion, which are
the procedural edges ``APPEAL_OF`` and ``ADVISES_ON`` of their own steps, not citations. Two
judgments of one case that such an edge ties (``PROCEDURAL_RELATIONS``, either way) have that
edge only: a Hoge Raad ruling that names the arrest under cassation and the conclusion in a
footnote does not cite them. The procedural steps run before this one. The edges of a judgment
are derived in full each time it is read: one its text no longer supports (made by an earlier
rule) is removed.

The ECLIs are read by ``core.ecli.cited_eclis``: a malformed one is repaired where the text shows
what was meant (a split LJN, NL and the court swapped, a range) and dropped otherwise, so it
makes no stub. A stub judgment no edge reaches any more goes at the end.

A decision before 2013 is cited by its LJN alone ("CRvB 12 januari 2010, LJN BK9271"): the
number of its ECLI (``ECLI:NL:CRVB:2010:BK9271``), unique over the courts. Such an LJN cites the
judgment in the graph whose ECLI has it for its number (``core.ecli.cited_ljns``, ``ljn_of``);
one that no judgment has, or that two have, cites nothing and makes no stub.

A decision of the ECHR is cited by application number ("EHRM 28 maart 2000, nr. 22492/93"):
``REFERS_TO`` to the decision of that number and date, or without a date to the only decision of
the number (``_echr_citations``).

An edge to a judgment cited by ECLI keeps the numbers of the paragraphs that name it
(``meta.paragraphs``: "4.3", "5.1", as the judgment prints them, ``core.judgments
.extract_sections``), so a list of citing judgments shows where each one cites without
reading its text; none when no numbered paragraph names it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from lawgraph.config.constants import (
    EDGE_STATUS_CANONIEK,
    RELATION_ADVISES_ON,
    RELATION_ANSWERS,
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
    RELATION_REFERS_TO,
)
from lawgraph.core.echr_citations import Cited, cited_in_dutch
from lawgraph.core.ecli import cited_eclis, cited_ljns, ljn_of
from lawgraph.core.judgments import body_text, extract_sections, parse_judgment
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.db.store import edge_key

from . import _echr_citations
from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-citation-linker"
# The edges that tie two judgments of one case; such a pair is not also a citation.
PROCEDURAL_RELATIONS = (
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
    RELATION_ADVISES_ON,
    RELATION_ANSWERS,
)


def cited(text: str, by_ljn: Mapping[str, str]) -> list[str]:
    """The ECLIs *text* cites: those it names, then those of the LJNs it names (*by_ljn*:
    LJN -> the ECLI of the judgment in the graph that has it), once each."""
    ljns = (by_ljn[ljn] for ljn in cited_ljns(text) if ljn in by_ljn)
    return list(dict.fromkeys([*cited_eclis(text), *ljns]))


def paragraphs_citing(
    paragraphs: list[dict[str, Any]], by_ljn: Mapping[str, str] | None = None
) -> dict[str, list[str]]:
    """Cited ECLI -> the numbers of the paragraphs that name it (or its LJN, *by_ljn*), in
    their order, each once; a paragraph without a number counts for none."""
    found: dict[str, list[str]] = {}
    for paragraph in paragraphs:
        number = paragraph.get("number")
        if not number:
            continue
        for ecli in cited(str(paragraph.get("text") or ""), by_ljn or {}):
            numbers = found.setdefault(ecli, [])
            if number not in numbers:
                numbers.append(str(number))
    return found


class RechtspraakCitationsSemanticPipeline(SemanticPipelineBase):
    """Detect ECLI cross-references in judgment texts and create REFERS_TO edges."""

    def __init__(
        self, store: Any, *, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that record key, so many
        judgments; the log names the last one read."""
        super().__init__(store)
        # (citing id, cited ECLI) -> the numbers of the paragraphs that name it
        self._places: dict[tuple[str, str], list[str]] = {}
        self._by_ljn: dict[str, str] | None = (
            None  # read once, when a text names an LJN
        )
        self.after = after
        self.limit = limit

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        self._places = {}
        pending, all_cited_eclis, read, by_appno = self._collect_references(
            iso_timestamp(since)
        )

        logger.info(
            "Found %d ECLI references in the text of %d judgments.",
            len(pending),
            len(read),
        )

        ecli_to_id = self._resolve_eclis(all_cited_eclis) if pending else {}
        tied = self._procedural_pairs(sorted({from_id for from_id, _ in pending}))
        kept = self._emit_edges(pending, ecli_to_id, tied, result)
        if by_appno:
            for from_id, keys in _echr_citations.link(
                self.store,
                by_appno,
                _echr_citations.decisions_index(self.store),
                source=SEMANTIC_SOURCE,
                result=result,
            ).items():
                kept.setdefault(from_id, set()).update(keys)
        removed = semantic_edges.remove_edges_from(
            self.store, RELATION_REFERS_TO, SEMANTIC_SOURCE, read, kept
        )
        logger.info("Removed %d citations the text does not name.", removed)
        stubs = semantic_rechtspraak.remove_unreached_judgment_stubs(self.store)
        logger.info("Removed %d stub judgments no edge reaches.", stubs)
        if self.after or self.limit is not None:
            last = self.last_judgment_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return result

    def _collect_references(
        self, since_iso: str | None = None
    ) -> tuple[list[tuple[str, str]], set[str], list[str], list[tuple[str, Cited]]]:
        """``(citing id, cited ECLI)`` pairs, the ECLIs cited, the ids of every judgment
        whose text was read, and ``(citing id, cited ECHR decision)`` pairs."""
        pending: list[tuple[str, str]] = []
        all_cited_eclis: set[str] = set()
        read: list[str] = []
        by_appno: list[tuple[str, Cited]] = []
        for judgment, xml in self._judgment_texts(
            since_iso, after=self.after, limit=self.limit
        ):
            try:
                root = parse_judgment(xml)
                text = body_text(root)
            except ValueError:
                continue
            if not judgment.node_id:
                continue
            read.append(judgment.node_id)
            source_ecli = str(judgment.props["ecli"]).upper()
            by_ljn = self._judgments_by_ljn() if cited_ljns(text) else {}
            where = paragraphs_citing(extract_sections(root), by_ljn)
            for ecli in cited(text, by_ljn):
                if ecli == source_ecli:
                    continue
                pending.append((judgment.node_id, ecli))
                all_cited_eclis.add(ecli)
                if where.get(ecli):
                    self._places[(judgment.node_id, ecli)] = where[ecli]
            by_appno += [(judgment.node_id, c) for c in cited_in_dutch(text)]
        return pending, all_cited_eclis, read, by_appno

    def _judgments_by_ljn(self) -> dict[str, str]:
        """LJN -> the ECLI of the one judgment in the graph whose number it is; an LJN two
        judgments have is left out."""
        if self._by_ljn is None:
            claims: dict[str, list[str]] = {}
            for ecli in semantic_rechtspraak.eclis_with_an_ljn(self.store):
                ljn = ljn_of(str(ecli))
                if ljn:
                    claims.setdefault(ljn, []).append(str(ecli).upper())
            self._by_ljn = {
                ljn: eclis[0] for ljn, eclis in claims.items() if len(eclis) == 1
            }
            logger.info("Read the LJNs of %d judgments.", len(self._by_ljn))
        return self._by_ljn

    def _procedural_pairs(self, ids: list[str]) -> set[tuple[str, str]]:
        """``(id, other)`` for every judgment of *ids* and the judgments a procedural edge
        ties it to."""
        return {
            (row[0], row[1])
            for row in semantic_rechtspraak.procedural_neighbours(
                self.store, ids, list(PROCEDURAL_RELATIONS)
            )
        }

    def _emit_edges(
        self,
        pending: list[tuple[str, str]],
        ecli_to_id: dict[str, str],
        tied: set[tuple[str, str]],
        result: PipelineResult,
    ) -> dict[str, set[str]]:
        """Write the edges, but none between judgments *tied* by a procedural edge; the
        keys of those written, per citing judgment."""
        kept: dict[str, set[str]] = {}
        left_out: set[tuple[str, str]] = set()
        edges = EdgeWriter(self.store, what=None)
        for from_id, cited_ecli in pending:
            to_id = ecli_to_id.get(cited_ecli)
            if not to_id:
                continue
            if (from_id, to_id) in tied:
                left_out.add((from_id, to_id))
                continue
            from_coll, from_key = from_id.split("/", 1)
            to_coll, to_key = to_id.split("/", 1)
            from_node = Node(
                collection=from_coll, type=NodeType.JUDGMENT, key=from_key, props={}
            )
            to_node = Node(
                collection=to_coll, type=NodeType.JUDGMENT, key=to_key, props={}
            )
            edge_doc = self._make_edge_doc(
                from_node=from_node,
                to_node=to_node,
                relation=RELATION_REFERS_TO,
                source=SEMANTIC_SOURCE,
                confidence=0.95,
                meta={
                    "cited_ecli": cited_ecli,
                    **(
                        {"paragraphs": paragraphs}
                        if (paragraphs := self._places.get((from_id, cited_ecli)))
                        else {}
                    ),
                },
                status=EDGE_STATUS_CANONIEK,
            )
            if edge_doc:
                edges.add_doc(edge_doc)
                kept.setdefault(from_id, set()).add(
                    edge_key(from_id, RELATION_REFERS_TO, to_id)
                )
        edges.flush_into(result)
        logger.info(
            "Left out %d citations between judgments tied by a procedural edge.",
            len(left_out),
        )
        return kept
