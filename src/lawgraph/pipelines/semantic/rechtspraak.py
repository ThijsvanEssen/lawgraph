"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.citations import CitationHit
from lawgraph.core.logging import get_logger
from lawgraph.core.mentions import ArticleMentions, find_mentions, footnote_paragraphs
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.provenance import REASON_BWB_METADATA_ARTICLE
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.counting import Store
from lawgraph.db.queries import unlinked_references as unlinked_queries

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)


EDGE_SOURCE = "rechtspraak-article-linker"
# A citation surer than this may make a stub of an article that is not loaded.
STUB_CONFIDENCE = 0.9
# The most citations of laws that are not in the graph a judgment keeps, in reading order.
MAX_UNRESOLVED_CITATIONS = 100


# The Rechtspraak editors link the law themselves: as sure as a link gets.
METADATA_CONFIDENCE = 1.0
ORIGIN_TEXT = "text"
ORIGIN_METADATA = "metadata"


@dataclass
class _Link:
    """One article a judgment cites: where its text names it (``cited``) and whether its
    metadata lists it (``metadata``)."""

    article: Node
    cited: ArticleMentions | None = None
    metadata: bool = False

    @property
    def confidence(self) -> float:
        if self.metadata:
            return METADATA_CONFIDENCE
        return self.cited.confidence if self.cited else 0.0

    def meta(self) -> dict[str, Any]:
        """The evidence on the edge: the mentions of the text (none for a metadata-only
        edge) and ``origin``, which of the two names the article."""
        meta = (
            self.cited.meta()
            if self.cited
            else {
                "reason": REASON_BWB_METADATA_ARTICLE,
                "mention_count": 0,
                "mentions": [],
            }
        )
        meta["origin"] = [
            *([ORIGIN_TEXT] if self.cited else []),
            *([ORIGIN_METADATA] if self.metadata else []),
        ]
        return meta


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class RechtspraakSemanticPipeline(SemanticPipelineBase):
    """Link Rechtspraak judgments to BWB articles via semantic edges.

    One edge per judgment and article; ``meta.mentions`` has every place in the judgment that
    cites the article (``core.mentions``): the paragraph, the span in its text, the lid or
    onderdeel it names. A citation in a footnote (``props.footnotes``) counts for the
    paragraph that refers to the footnote, with its label (``footnote``). The edges of a
    judgment are derived in full each time it is read: one its text no longer makes (an
    earlier rule, an earlier text) goes. A citation of a law that is not in the graph
    (``artikel 392 Rv``) has no article to point at: the judgment keeps it in
    ``props.unresolved_citations``, written only when it changed. How many of the articles it
    cites it could not link, of a law or an article not in the graph, is kept in
    ``lg_unlinked_references``: what ``completeness.references`` of the API says.
    """

    def __init__(
        self, *, store: Store, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that judgment key, so
        many judgments; the log names the last one read."""
        super().__init__(store=store)
        self.after = after
        self.limit = limit

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

        mapping, shared = self._load_code_choices()
        instrument_aliases = self._load_instrument_aliases()
        # "EP" is the First Protocol in a judgment that also names the EVRM; a judgment
        # cites no law that came to be after its date, and by a code several laws have
        # the one in force on its date
        extractor = build_extractor(
            mapping,
            instrument_aliases,
            self._load_context_aliases(mapping),
            self._load_law_dates(),
            shared,
        )

        def detector(on: str | None) -> Callable[[str], list[CitationHit]]:
            def detect(text: str) -> list[CitationHit]:
                hits = detect_in_text(
                    text, extractor, every_occurrence=True, unknown_laws=True, on=on
                )
                return [hit for hit in hits if hit.kind == "article"]

            return detect

        logger.info(
            "Processing Rechtspraak judgments for article references (since=%s).",
            describe_since(since),
        )

        edges = EdgeWriter(self.store, what=None, remembers=True)
        read: list[str] = []
        unlinked: dict[str, int] = {}
        with NodeWriter(self.store) as nodes:
            for judgment, paragraphs in self._judgment_paragraphs(
                since_iso, after=self.after, limit=self.limit
            ):
                read.append(str(judgment.node_id))
                decided = str(judgment.props.get("date") or "")[:10] or None
                links, unresolved, missed = self._links_of(
                    judgment, paragraphs, detector(decided)
                )
                for link in links.values():
                    edges.add_doc(
                        self._make_edge_doc(
                            from_node=judgment,
                            to_node=link.article,
                            relation=RELATION_REFERS_TO,
                            source=EDGE_SOURCE,
                            confidence=link.confidence,
                            meta=link.meta(),
                        )
                    )
                self._keep_unresolved(judgment, unresolved, nodes, result)
                unlinked[str(judgment.node_id)] = missed

        edges.flush_into(result)
        whole = since is None and not self.after and self.limit is None
        unlinked_queries.keep_unlinked(self.store, EDGE_SOURCE, unlinked, whole=whole)
        removed = edges.remove_stale(RELATION_REFERS_TO, EDGE_SOURCE, read)
        logger.info(
            "Removed %d article citations the text and the metadata no longer make.",
            removed,
        )
        if self.after or self.limit is not None:
            last = self.last_judgment_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return result

    @staticmethod
    def _keep_unresolved(
        judgment: Node,
        unresolved: list[dict[str, Any]],
        nodes: NodeWriter,
        result: PipelineResult,
    ) -> None:
        """Write ``props.unresolved_citations`` of *judgment* when it changed; null when the
        judgment cites no law that is not in the graph."""
        kept = unresolved[:MAX_UNRESOLVED_CITATIONS] or None
        if kept == judgment.props.get("unresolved_citations"):
            return
        nodes.add(
            Node(
                collection=COLLECTION_JUDGMENTS,
                key=judgment.key,
                props={"unresolved_citations": kept},
            )
        )
        result.updated += 1

    def _links_of(
        self,
        judgment: Node,
        paragraphs: list[dict[str, Any]],
        detect: Callable[[str], list[CitationHit]],
    ) -> tuple[dict[str, _Link], list[dict[str, Any]], int]:
        """``(links, unresolved, missed)`` of one judgment: the articles its text and its
        metadata name (by article id), the citations of laws not in the graph, and how many
        references (text and metadata) no article of the graph could be found for."""
        notes = footnote_paragraphs(paragraphs, judgment.props.get("footnotes") or [])
        links: dict[str, _Link] = {}
        unresolved: list[dict[str, Any]] = []
        gaps: set[tuple[str | None, str | None]] = set()
        missed = 0
        for cited in find_mentions([*paragraphs, *notes], detect).values():
            if cited.unknown_law:
                unresolved.append(cited.unresolved())
                gaps.add((cited.unknown_law, cited.article_number))
                missed += 1
                continue
            article = self._resolve_article(cited)
            if article is None:
                gaps.add((cited.bwb_id or cited.celex, cited.article_number))
                missed += 1
                continue
            links[str(article.node_id)] = _Link(article, cited)
        missed += self._add_metadata_links(judgment, links, gaps)
        return links, unresolved, missed

    def _add_metadata_links(
        self,
        judgment: Node,
        links: dict[str, _Link],
        gaps: set[tuple[str | None, str | None]],
    ) -> int:
        """Mark in *links* the articles the metadata of *judgment* lists (``props.law_references``),
        adding an edge for one its text does not name. How many it lists that are no article of
        the graph, a gap the text did not already leave (*gaps*). A reference to the law only
        names no article."""
        missed = 0
        for ref in judgment.props.get("law_references") or []:
            number = ref.get("article")
            if not number:
                continue
            article = self._cited_article(
                ref["bwb_id"],
                number,
                celex=False,
                confidence=METADATA_CONFIDENCE,
                min_confidence=STUB_CONFIDENCE,
            )
            if article is not None:
                links.setdefault(str(article.node_id), _Link(article)).metadata = True
            elif (ref["bwb_id"], number) not in gaps:
                gaps.add((ref["bwb_id"], number))
                missed += 1
        return missed

    def _resolve_article(self, cited: ArticleMentions) -> Node | None:
        law_id = cited.bwb_id or cited.celex
        if not law_id or not cited.article_number:
            return None
        return self._cited_article(
            law_id,
            cited.article_number,
            celex=cited.bwb_id is None,
            confidence=cited.confidence,
            min_confidence=STUB_CONFIDENCE,
        )
