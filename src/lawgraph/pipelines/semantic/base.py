from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.core.aliases import (
    InstrumentAliasMap,
    code_choices,
    curated_abbreviations,
    curated_context_abbreviations,
    instrument_names,
    law_dates,
    normalize_instrument_id,
)
from lawgraph.core.citations import LawDates, number_shape
from lawgraph.core.ecli import is_valid_ecli
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, make_node_key
from lawgraph.db import make_edge_doc
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


CodeMapping = dict[str, str]


@dataclass(frozen=True)
class _LawArticles:
    """What the loaded articles of one law tell about a number cited of it."""

    shapes: frozenset[str]  # ``core.citations.number_shape`` of its current articles
    stubs: frozenset[str]  # keys of its stub articles
    historical: dict[str, str]  # last number -> key of an article no longer in force


# Judgments are tens of KB each: fewer per cursor batch than the default 1000.
JUDGMENT_BATCH_SIZE = 100


class SemanticPipelineBase(PipelineBase):
    """Shared base for all semantic pipelines.

    Provides alias resolution and edge helpers so subclasses only implement run().
    """

    def __init__(self, store: Any) -> None:
        super().__init__(store=store)
        # (collection, key) -> lightweight Node, or None when known to be absent.
        self._node_cache: dict[tuple[str, str], Node | None] = {}
        # the key of the last judgment a run read (``_judgment_paragraphs``, ``_judgment_texts``):
        # where a slice ends
        self.last_judgment_read: str | None = None
        # law id -> what its loaded articles say (``_law``), read once per law and run.
        self._laws: dict[str, _LawArticles | None] = {}

    def _cited_article(
        self,
        law_id: str,
        number: str,
        *,
        celex: bool,
        confidence: float,
        min_confidence: float,
    ) -> Node | None:
        """The article a citation of *number* of a law points at, or ``None``.

        The article with that number (a stub of a loaded law only when the rules below
        would make it); else, of a law whose articles are loaded, the
        historical article that last had it (a repealed or renumbered article, cited by
        a text from before), and nothing for a number of a shape the law never uses
        (``140.1 Sr``). Else a stub, when the citation is sure enough: an article of a law
        that is not loaded, or one the loaded text lacks.
        """
        key = make_node_key(law_id, number)
        node = self._lookup_node(COLLECTION_ARTICLES, key)
        law = self._law(law_id, "celex" if celex else "bwb_id")
        if node is not None and (law is None or key not in law.stubs):
            return node
        if law is not None:
            historical = law.historical.get(number)
            if historical is not None:
                return self._lookup_node(COLLECTION_ARTICLES, historical)
            if number_shape(number) not in law.shapes:
                return None
        if node is not None:  # a stub made before: the rules above keep it
            return node
        if confidence < min_confidence:
            return None
        props: dict[str, Any] = {
            ("celex" if celex else "bwb_id"): law_id,
            "article_number": number,
        }
        node = self.store.ensure_stub_node(COLLECTION_ARTICLES, key, props=props)
        self._remember_node(node)
        return node

    def _law(self, law_id: str, field: str) -> _LawArticles | None:
        """The shapes and the historical numbers of a law's articles; ``None`` when
        none of its articles is loaded (only stubs, or nothing)."""
        if law_id not in self._laws:
            rows = list(semantic_bwb.law_articles(self.store, field, law_id))
            current = [r["number"] for r in rows if r["number"] and not r["stub"]]
            self._laws[law_id] = (
                _LawArticles(
                    shapes=frozenset(number_shape(n) for n in current),
                    stubs=frozenset(r["key"] for r in rows if r["stub"]),
                    historical={
                        r["last_number"]: r["key"]
                        for r in rows
                        if r["last_number"] and not r["number"]
                    },
                )
                if current
                else None
            )
        return self._laws[law_id]

    def _resolve_instrument(
        self, *, bwb_id: str | None = None, celex: str | None = None
    ) -> Node | None:
        """The instrument with this BWB id or CELEX number, when it is in the graph."""
        key = bwb_id or celex
        if not key:
            return None
        return self._lookup_node(COLLECTION_INSTRUMENTS, make_node_key(key))

    # ---------------------------------------------------------------- progress

    def _track[T](
        self, items: Iterable[T], what: str, *, total: int | None = None
    ) -> Iterator[T]:
        """Pass *items* on and report the progress of the loop that takes them.

        Every semantic pipeline runs its main loop through this (or through
        ``_judgment_texts``): a status line in the terminal, one a minute in a log file, and
        a summary with the duration at the end. A record the loop leaves out goes to
        ``self.progress``; the pipeline ends with ``self.add_outcomes(result)``.
        """
        return self._loop(what, total=total).track(items)

    # --------------------------------------------------------------- judgments

    def _judgment_texts(
        self,
        since_iso: str | None = None,
        *,
        after: str | None = None,
        limit: int | None = None,
    ) -> Iterator[tuple[Node, str]]:
        """``(judgment node, XML)`` of every stored Rechtspraak judgment, from raw_sources.

        The XML is not kept on the judgment node (it holds the summary, the text and the
        paragraphs already): it is read from the payload store, where retrieve put it. The
        node is the one normalize makes of the same ECLI. A slice: past the record key
        *after*, *limit* of them; ``last_judgment_read`` is the record key it ended at.
        """
        total = None
        if not since_iso and not after and limit is None:  # from the index
            total = raw_queries.count_judgment_records(self.store)
        rows = raw_queries.judgment_payload_refs(
            self.store,
            since_iso=since_iso,
            batch_size=JUDGMENT_BATCH_SIZE,
            after=after,
            limit=limit,
        )
        self.last_judgment_read = None
        progress = self._loop("judgments", total=total)
        for row in progress.track(self.store.with_payloads(rows)):
            self.last_judgment_read = row.get("key") or self.last_judgment_read
            ecli = str(row.get("ecli") or "").strip()
            if not ecli or row.get("payload_text") is None:
                progress.skip("no judgment XML stored", ecli or row.get("key"))
                continue
            node = Node.skeleton(
                COLLECTION_JUDGMENTS, make_node_key(ecli), {"ecli": ecli}
            )
            yield node, str(row["payload_text"])

    def _judgment_paragraphs(
        self,
        since_iso: str | None = None,
        *,
        after: str | None = None,
        limit: int | None = None,
    ) -> Iterator[tuple[Node, list[dict[str, Any]]]]:
        """``(judgment node, paragraphs)`` of every judgment ``normalize rechtspraak`` made.

        The paragraphs are the ones the API serves (``{id, number, kind, text}``), so what a
        pipeline records about a paragraph is found again by its id. With *since_iso* only
        the judgments retrieved from that moment on; a slice: past the judgment key *after*,
        *limit* of them.
        """
        eclis = self._recent_eclis(since_iso) if since_iso else None
        total = None
        if not since_iso and not after and limit is None:  # from the index
            total = semantic_rechtspraak.count_rechtspraak_judgments(self.store)
        rows = semantic_rechtspraak.judgment_paragraphs(
            self.store,
            eclis=eclis,
            batch_size=JUDGMENT_BATCH_SIZE,
            after=after,
            limit=limit,
        )
        self.last_judgment_read = None
        for row in self._track(rows, "judgments", total=total):
            node = Node.from_document(COLLECTION_JUDGMENTS, row)
            # with or without paragraphs: where a slice ends
            self.last_judgment_read = node.key
            paragraphs = node.props.get("paragraphs")
            if paragraphs:
                yield node, paragraphs

    def _recent_eclis(self, since_iso: str) -> list[str]:
        """The ECLIs of the judgments retrieved at or after *since_iso*."""
        rows = raw_queries.judgment_eclis_fetched_since(self.store, since_iso)
        return sorted({str(e) for e in rows if e})

    # ------------------------------------------------------------ node lookup

    def _lookup_node(self, collection: str, key: str) -> Node | None:
        """``get_node`` with a per-run cache of hits *and* misses.

        Citation targets repeat a lot ("artikel 1", "art. 287 Sr"), so this turns
        one lookup per citation into one per distinct target. The returned node
        is a skeleton (key/collection/type, no props): use it as an edge endpoint,
        not to read data. Call ``_remember_node`` after creating a stub, and
        ``_prefetch_nodes`` to fill the cache for a whole batch in one query.
        """
        if (collection, key) not in self._node_cache:
            # Does it exist: a lookup in the primary index. ``get_node`` would have the whole
            # document sent over, an article with its text, to throw it away.
            self._prefetch_nodes(collection, [key])
        return self._node_cache[(collection, key)]

    def _remember_node(self, node: Node | None) -> None:
        """Record a node created during the run (e.g. a stub) in the lookup cache."""
        if node is not None and node.key is not None:
            self._node_cache[(node.collection, node.key)] = Node.skeleton(
                node.collection, node.key
            )

    def _prefetch_nodes(self, collection: str, keys: Iterable[str]) -> None:
        """Resolve many keys with one bulk lookup so ``_lookup_node`` never hits the DB."""
        missing = {k for k in keys if (collection, k) not in self._node_cache}
        for key in self.store.existing_keys(collection, missing):
            self._node_cache[(collection, key)] = Node.skeleton(collection, key)
            missing.discard(key)
        for key in missing:
            self._node_cache[(collection, key)] = None

    def _resolve_eclis(self, eclis: set[str]) -> dict[str, str]:
        """Map each ECLI to a judgment node id, stubbing the ones not in the corpus.

        One lookup for the whole set; a judgment cited from outside the corpus
        gets a stub so the citation edge still has both endpoints. A malformed ECLI
        (``core.ecli.is_valid_ecli``) gets none and stays unmapped.
        """
        by_ecli: dict[str, str] = {}
        for row in semantic_rechtspraak.judgment_ids_by_ecli(self.store, sorted(eclis)):
            ecli, node_id = (row.get("ecli") or "").upper(), row.get("id") or ""
            if ecli and node_id:
                by_ecli[ecli] = node_id

        for ecli in eclis:
            if ecli in by_ecli or not is_valid_ecli(ecli):
                continue
            node = self.store.ensure_stub_node(
                COLLECTION_JUDGMENTS,
                make_node_key(ecli),
                props={"ecli": ecli},
            )
            if node and node.node_id:
                by_ecli[ecli] = node.node_id
        return by_ecli

    # ------------------------------------------------------------------ config

    def _load_code_aliases(self) -> CodeMapping:
        """Abbreviation → bwb_id/celex of the instruments in the graph
        (``core.aliases.code_aliases``)."""
        return self._load_code_choices()[0]

    def _load_code_choices(self) -> tuple[CodeMapping, dict[str, dict[str, str]]]:
        """``_load_code_aliases`` and the abbreviations several laws have
        (``core.aliases.code_choices``)."""
        return code_choices(
            semantic_bwb.code_alias_rows(self.store), curated_abbreviations()
        )

    def _load_context_aliases(
        self, codes: CodeMapping
    ) -> dict[str, tuple[str, list[str]]]:
        """Abbreviation -> (law id, the words a text must also name) for the laws among
        *codes* (``in_context`` of ``curated instrument-abbreviations``: "EP" beside "EVRM")."""
        present = {normalize_instrument_id(law_id) for law_id in codes.values()}
        return {
            abbreviation: (law_id, list(words))
            for law_id, in_context in curated_context_abbreviations().items()
            if law_id in present
            for abbreviation, words in in_context.items()
        }

    def _load_instrument_aliases(self) -> InstrumentAliasMap:
        """Law name -> ``(bwb_id, celex)`` of the instruments with a BWB id or a CELEX
        number: their ``title`` and ``citation_title`` (not ``short_title``, which
        ``_load_code_aliases`` reads), and such a name without its year
        (``core.aliases.instrument_names``). A failing query fails the step."""
        return instrument_names(semantic_bwb.instrument_alias_rows(self.store))

    def _load_law_dates(self) -> dict[str, LawDates]:
        """Law id -> when the instrument came to be, came into force and expired
        (``core.aliases.law_dates``)."""
        return law_dates(semantic_bwb.law_date_rows(self.store))

    # ------------------------------------------------------------------ edges

    def _make_edge_doc(
        self,
        *,
        from_node: Node,
        to_node: Node,
        relation: str,
        source: str,
        confidence: float = 0.0,
        meta: dict[str, Any] | None = None,
        status: str = EDGE_STATUS_CANONIEK,
    ) -> dict[str, Any] | None:
        """Build an edge document dict without writing to the DB.

        Returns None when from_node or to_node have no id (skip silently).
        """
        if not from_node.node_id or not to_node.node_id:
            return None
        return make_edge_doc(
            from_node.node_id,
            to_node.node_id,
            relation,
            source=source,
            confidence=confidence,
            status=status,
            meta=meta,
        )
