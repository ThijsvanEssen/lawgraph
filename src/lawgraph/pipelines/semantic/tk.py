"""Semantic linkage pipeline that connects TK documents to the articles they cite."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.aliases import AliasMatcher, InstrumentAliasMap
from lawgraph.core.citations import (
    ARTICLE_HEAD_RE,
    LAW_CONNECTOR_RE,
    CitationHit,
    DutchCitationExtractor,
    hit_reason,
    make_snippet,
)
from lawgraph.core.identifiers import parse_celex
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.paper_text import PaperText
from lawgraph.core.qualifiers import parse_qualifier
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import tk as semantic_tk

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-article-linker"
# A citation surer than this may make a stub of an article that is not loaded.
STUB_CONFIDENCE = 0.85

# ---------------------------------------------------------------------------
# Instrument-level hit collectors
# ---------------------------------------------------------------------------


class NamedActs:
    """The laws of the graph a text names: by a name (title or citation title), matched in
    one pass without regard to case (``AliasMatcher``), or by an abbreviation
    (``core.aliases.code_aliases``: the short title, the WTI abbreviations, the curated ones),
    matched as written: "EVRM" is the Convention, "evrm" nothing. An abbreviation that is
    the law of an article citation ("art. 8 EVRM") belongs to that citation, which cites the
    article; only one that stands alone names the law."""

    def __init__(
        self, aliases: InstrumentAliasMap, codes: Mapping[str, str] | None = None
    ) -> None:
        self._targets = [
            (bwb_id, celex) for bwb_id, celex in aliases.values() if bwb_id or celex
        ]
        self._matcher = AliasMatcher(
            label for label, (bwb_id, celex) in aliases.items() if bwb_id or celex
        )
        self._codes = dict(codes or {})
        self._code_re = (
            re.compile(
                r"(?<![\w-])(?:"
                + "|".join(
                    re.escape(code)
                    for code in sorted(self._codes, key=len, reverse=True)
                )
                + r")(?![\w-])"
            )
            if self._codes
            else None
        )

    def collect_hits(self, text: str, record: Callable[[CitationHit], None]) -> None:
        for order, start, end in self._matcher.first_matches(text):
            bwb_id, celex = self._targets[order]
            record(_instrument_hit(text, start, end, bwb_id, celex))
        if self._code_re is None:
            return
        seen: set[str] = set()
        for match in self._code_re.finditer(text):
            law_id = self._codes[match.group(0)]
            if law_id in seen or _ends_a_citation_head(text, match.start()):
                continue
            seen.add(law_id)
            celex = law_id if parse_celex(law_id) else None
            bwb_id = None if celex else law_id
            record(_instrument_hit(text, match.start(), match.end(), bwb_id, celex))


# How far back an article citation may start before the law it names.
_HEAD_REACH = 200


def _ends_a_citation_head(text: str, start: int) -> bool:
    """Whether the law at *start* is the law of an article citation: an article head
    (``artikel 8, eerste lid,``) and its connector (``van het``) end right there."""
    offset = max(0, start - _HEAD_REACH)
    window = text[offset:start]
    for head in ARTICLE_HEAD_RE.finditer(window):
        connector = LAW_CONNECTOR_RE.match(window, head.end())
        if connector is not None and connector.end() == len(window):
            return True
    return False


def _instrument_hit(
    text: str, start: int, end: int, bwb_id: str | None, celex: str | None
) -> CitationHit:
    return CitationHit(
        kind="instrument",
        bwb_id=bwb_id,
        celex=celex,
        confidence=0.6,
        raw_match=text[start:end],
        snippet=make_snippet(text, (start, end)),
        start=start,
        end=end,
    )


def detect_tk_citations(
    text: str,
    code_aliases: dict[str, str],
    instrument_aliases: InstrumentAliasMap,
) -> list[CitationHit]:
    """Detect article and instrument citations in the text of a TK document."""
    if not text:
        return []

    return _collect_tk_hits(
        text,
        build_extractor(code_aliases, instrument_aliases),
        NamedActs(instrument_aliases, code_aliases),
    )


def _collect_tk_hits(
    text: str,
    extractor: DutchCitationExtractor,
    named_acts: NamedActs,
) -> list[CitationHit]:
    """Registry-driven article hits plus every instrument-level TK pattern."""
    return detect_in_text(text, extractor, extra=named_acts.collect_hits)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TKSemanticPipeline(SemanticPipelineBase):
    """Pipeline connecting TK documents to the articles and instruments they cite.

    The edges of a document are derived in full each time it is read: one its words no
    longer make (an earlier rule, an earlier text) goes. An edge says where its citation
    stands in what ``/api/documents/{key}`` serves (``core.paper_text``): ``meta.place``,
    ``{part, start, end}`` with ``part`` ``title``, ``text`` (and ``section_id``) or
    ``footnote`` (and ``footnote``, ``footnote_id``), and ``meta.snippet`` from that part
    alone."""

    def __init__(
        self, *, store: Any, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that document key, so
        many documents; the log names the last one read."""
        super().__init__(store=store)
        self.after = after
        self.limit = limit
        self.last_document_read: str | None = None

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

        code_aliases = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not code_aliases and not instrument_aliases:
            logger.warning(
                "No instrument or code aliases configured for TK semantic linking."
            )

        extractor = build_extractor(code_aliases, instrument_aliases)
        named_acts = NamedActs(instrument_aliases, code_aliases)

        logger.info(
            "Processing TK documents for semantic linking (since=%s).",
            describe_since(since),
        )

        edges = EdgeWriter(self.store, what=None, remembers=True)
        read: list[str] = []

        documents = self._load_tk_documents(since_iso=since_iso)
        for document in self._track(documents, "TK documents"):
            self.last_document_read = document.key
            read.append(str(document.node_id))
            words = PaperText.of(document.props)
            if not words.text:
                result.skipped += 1
                continue

            for hit in _collect_tk_hits(words.text, extractor, named_acts):
                edges.add_doc(self._edge_of(document, hit, words))

        edges.flush_into(result)
        removed = edges.remove_stale(RELATION_REFERS_TO, SEMANTIC_SOURCE, read)
        logger.info("Removed %d citations the documents no longer make.", removed)
        if self.after or self.limit is not None:
            last = self.last_document_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return result

    def _edge_of(
        self, document: Node, hit: CitationHit, words: PaperText
    ) -> dict[str, Any] | None:
        """The REFERS_TO edge of one hit, or None when its target is not in the graph;
        *words*: what was read of the paper, which places the hit."""
        target_node = self._resolve_target_node(hit)
        if not target_node:
            return None
        meta = {
            k: v
            for k, v in {
                "raw_match": hit.raw_match,
                "snippet": hit.snippet,
                "reason": hit_reason(hit),
                "qualifier": hit.qualifier,
                **parse_qualifier(hit.qualifier).to_dict(),
            }.items()
            if v
        }
        place, snippet = words.place(hit.start, hit.end)
        # null for a citation over two parts: a relink clears an earlier place
        meta["place"] = place
        if snippet:
            meta["snippet"] = snippet
        return self._make_edge_doc(
            from_node=document,
            to_node=target_node,
            relation=RELATION_REFERS_TO,
            source=SEMANTIC_SOURCE,
            confidence=hit.confidence,
            meta=meta,
        )

    def _load_tk_documents(self, *, since_iso: str | None = None) -> Iterable[Node]:
        """TK documents; only a Document may be the source of a REFERS_TO edge."""
        ids: list[str] | None = None
        if since_iso is not None:
            recent_ids = self._recent_external_ids(since_iso)
            if not recent_ids:
                return
            ids = sorted(recent_ids)
        for doc in semantic_tk.tk_documents(
            self.store, ids, after=self.after, limit=self.limit
        ):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)

    def _recent_external_ids(self, since_iso: str) -> set[str]:
        """External ids of TK documents fetched at or after *since_iso*."""
        rows = raw_queries.tk_document_ids_fetched_since(self.store, since_iso)
        return {str(row) for row in rows if isinstance(row, str)}

    def _resolve_target_node(self, hit: CitationHit) -> Node | None:
        law_id = hit.bwb_id or hit.celex
        if hit.kind == "article" and law_id and hit.article_number:
            node = self._cited_article(
                law_id,
                hit.article_number,
                celex=hit.bwb_id is None,
                confidence=hit.confidence,
                min_confidence=STUB_CONFIDENCE,
            )
            if node is None:
                logger.debug(
                    "TK semantic: no node found for %s %s (confidence=%.2f)",
                    law_id,
                    hit.article_number,
                    hit.confidence,
                )
            return node

        if hit.celex:
            key = make_node_key(hit.celex)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for CELEX %s", hit.celex)
            return node

        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for BWB %s", hit.bwb_id)
            return node

        return None
