"""``REFERS_TO`` between judgments: the ECLIs a judgment names in its text.

Only the text the court or advocate-general wrote is read (``core.judgments.body_text``), never
the metadata: its ``dcterms:relation`` names the earlier instance and the conclusion, which are
the procedural edges ``APPEAL_OF`` and ``ADVISES_ON`` of their own steps, not citations. The
edges of a judgment are derived in full each time it is read: one its text no longer supports
(made by an earlier rule) is removed.
"""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    EDGE_STATUS_CANONIEK,
    RELATION_REFERS_TO,
)
from lawgraph.core.identifiers import find_eclis
from lawgraph.core.judgments import body_text, parse_judgment
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries
from lawgraph.db.store import edge_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-citation-linker"


class RechtspraakCitationsSemanticPipeline(SemanticPipelineBase):
    """Detect ECLI cross-references in judgment texts and create REFERS_TO edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        pending, all_cited_eclis, read = self._collect_references(iso_timestamp(since))

        logger.info(
            "Found %d ECLI references in the text of %d judgments.",
            len(pending),
            len(read),
        )

        ecli_to_id = self._resolve_eclis(all_cited_eclis) if pending else {}
        kept = self._emit_edges(pending, ecli_to_id, result)
        removed = semantic_queries.remove_edges_from(
            self.store, RELATION_REFERS_TO, SEMANTIC_SOURCE, read, kept
        )
        logger.info("Removed %d citations the text does not name.", removed)
        return result

    def _collect_references(
        self, since_iso: str | None = None
    ) -> tuple[list[tuple[str, str]], set[str], list[str]]:
        """``(citing id, cited ECLI)`` pairs, the ECLIs cited, and the ids of every
        judgment whose text was read."""
        pending: list[tuple[str, str]] = []
        all_cited_eclis: set[str] = set()
        read: list[str] = []
        for judgment, xml in self._judgment_texts(since_iso):
            try:
                text = body_text(parse_judgment(xml))
            except ValueError:
                continue
            if not judgment.arango_id:
                continue
            read.append(judgment.arango_id)
            source_ecli = str(judgment.props["ecli"]).upper()
            for ecli in find_eclis(text):
                if ecli == source_ecli:
                    continue
                pending.append((judgment.arango_id, ecli))
                all_cited_eclis.add(ecli)
        return pending, all_cited_eclis, read

    def _emit_edges(
        self,
        pending: list[tuple[str, str]],
        ecli_to_id: dict[str, str],
        result: PipelineResult,
    ) -> dict[str, set[str]]:
        """Write the edges; the keys of those written, per citing judgment."""
        kept: dict[str, set[str]] = {}
        edges = EdgeWriter(self.store, what=None)
        for from_id, cited_ecli in pending:
            to_id = ecli_to_id.get(cited_ecli)
            if not to_id:
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
                meta={"cited_ecli": cited_ecli},
                status=EDGE_STATUS_CANONIEK,
            )
            if edge_doc:
                edges.add_doc(edge_doc)
                kept.setdefault(from_id, set()).add(
                    edge_key(from_id, RELATION_REFERS_TO, to_id)
                )
        edges.flush_into(result)
        return kept
