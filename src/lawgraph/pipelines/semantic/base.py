from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.core.aliases import InstrumentAliasMap, normalize_instrument_id
from lawgraph.core.citations import number_shape
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.progress import Progress
from lawgraph.db import make_edge_doc
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import semantic as semantic_queries
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

T = TypeVar("T")

CodeMapping = dict[str, str]


def _skeleton(node: Node) -> Node:
    return Node(
        collection=node.collection,
        type=node.type,
        key=node.key,
        props={},
        _skip_validation=True,
    )


# The collections a citation points into, and the type of their nodes.
_TARGET_TYPES = {
    COLLECTION_ARTICLES: NodeType.ARTICLE,
    COLLECTION_INSTRUMENTS: NodeType.INSTRUMENT,
    COLLECTION_JUDGMENTS: NodeType.JUDGMENT,
}


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
        node = self.store.ensure_stub_node(
            COLLECTION_ARTICLES, key, NodeType.ARTICLE, props=props
        )
        self._remember_node(node)
        return node

    def _law(self, law_id: str, field: str) -> _LawArticles | None:
        """The shapes and the historical numbers of a law's articles; ``None`` when
        none of its articles is loaded (only stubs, or nothing)."""
        if law_id not in self._laws:
            rows = list(semantic_queries.law_articles(self.store, field, law_id))
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

    def _track(
        self, items: Iterable[T], what: str, *, total: int | None = None
    ) -> Iterator[T]:
        """Pass *items* on and report the progress of the loop that takes them.

        Every semantic pipeline runs its main loop through this (or through
        ``_judgment_texts``): a status line in the terminal, one a minute in a log file, and
        a summary with the duration at the end.
        """
        return Progress(what, total=total).track(items)

    # --------------------------------------------------------------- judgments

    def _judgment_texts(
        self, since_iso: str | None = None
    ) -> Iterator[tuple[Node, str]]:
        """``(judgment node, XML)`` of every stored Rechtspraak judgment, from raw_sources.

        The XML is not kept on the judgment node (it holds the summary, the text and the
        paragraphs already): it is read from the payload store, where retrieve put it. The
        node is the one normalize makes of the same ECLI.
        """
        total = None
        if (
            not since_iso
        ):  # from the index; with a date every record would have to be read
            total = raw_queries.count_judgment_records(self.store)
        rows = raw_queries.judgment_payload_refs(
            self.store, since_iso=since_iso, batch_size=JUDGMENT_BATCH_SIZE
        )
        for row in self._track(
            self.store.with_payloads(rows), "judgments", total=total
        ):
            ecli = str(row.get("ecli") or "").strip()
            if not ecli or row.get("payload_text") is None:
                continue
            node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=make_node_key(ecli),
                props={"ecli": ecli},
                _skip_validation=True,
            )
            yield node, str(row["payload_text"])

    def _judgment_paragraphs(
        self, since_iso: str | None = None
    ) -> Iterator[tuple[Node, list[dict[str, Any]]]]:
        """``(judgment node, paragraphs)`` of every judgment ``normalize rechtspraak`` made.

        The paragraphs are the ones the API serves (``{id, number, kind, text}``), so what a
        pipeline records about a paragraph is found again by its id. With *since_iso* only
        the judgments retrieved from that moment on.
        """
        eclis = self._recent_eclis(since_iso) if since_iso else None
        total = None
        if not since_iso:  # from the index; with a date every judgment would be read
            total = semantic_queries.count_rechtspraak_judgments(self.store)
        rows = semantic_queries.judgment_paragraphs(
            self.store, eclis=eclis, batch_size=JUDGMENT_BATCH_SIZE
        )
        for row in self._track(rows, "judgments", total=total):
            node = Node.from_document(COLLECTION_JUDGMENTS, row)
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
            self._prefetch_nodes(collection, [key], _TARGET_TYPES[collection])
        return self._node_cache[(collection, key)]

    def _remember_node(self, node: Node | None) -> None:
        """Record a node created during the run (e.g. a stub) in the lookup cache."""
        if node is not None and node.key is not None:
            self._node_cache[(node.collection, node.key)] = _skeleton(node)

    def _prefetch_nodes(
        self, collection: str, keys: Iterable[str], node_type: NodeType
    ) -> None:
        """Resolve many keys with one bulk lookup so ``_lookup_node`` never hits the DB."""
        missing = {k for k in keys if (collection, k) not in self._node_cache}
        for key in self.store.existing_keys(collection, missing):
            self._node_cache[(collection, key)] = Node(
                collection=collection,
                type=node_type,
                key=key,
                props={},
                _skip_validation=True,
            )
            missing.discard(key)
        for key in missing:
            self._node_cache[(collection, key)] = None

    def _resolve_eclis(self, eclis: set[str]) -> dict[str, str]:
        """Map each ECLI to a judgment node id, stubbing the ones not in the corpus.

        One lookup for the whole set; a judgment cited from outside the corpus
        gets a stub so the citation edge still has both endpoints.
        """
        by_ecli: dict[str, str] = {}
        for row in semantic_queries.judgment_ids_by_ecli(self.store, sorted(eclis)):
            ecli, node_id = (row.get("ecli") or "").upper(), row.get("id") or ""
            if ecli and node_id:
                by_ecli[ecli] = node_id

        for ecli in eclis:
            if ecli in by_ecli:
                continue
            node = self.store.ensure_stub_node(
                COLLECTION_JUDGMENTS,
                make_node_key(ecli),
                NodeType.JUDGMENT,
                props={"ecli": ecli},
            )
            if node and node.arango_id:
                by_ecli[ecli] = node.arango_id
        return by_ecli

    # ------------------------------------------------------------------ config

    @staticmethod
    def _load_alias_index(
        rows: Iterable[dict[str, Any]], key_field: str, value_fields: tuple[str, ...]
    ) -> dict[str, str]:
        """Build a normalised key → value alias mapping from query rows.

        For each row of *rows*, the value at *key_field* becomes the
        dict key. The first non-empty value found across *value_fields* (in
        order) becomes the dict value. First-write-wins — subsequent rows that
        produce the same key are ignored. Keys and values are stripped.
        A failing query fails the step: without the names every citation would be missed.
        """
        index: dict[str, str] = {}
        for row in rows:
            key = str(row.get(key_field) or "").strip()
            if not key:
                continue
            if key in index:
                continue
            for field in value_fields:
                val = row.get(field)
                if val:
                    index[key] = str(val).strip()
                    break
        return index

    def _load_code_aliases(self) -> CodeMapping:
        """Build short_title → bwb_id/celex map from instruments in the graph."""
        return self._load_alias_index(
            semantic_queries.code_alias_rows(self.store),
            "short_title",
            ("bwb_id", "celex"),
        )

    def _load_instrument_aliases(self) -> InstrumentAliasMap:
        """Query the instruments collection to build a name → (bwb_id, celex) map.

        Only includes instruments that have a bwb_id or celex prop. The
        ``title`` and ``citation_title`` props are indexed as keys (not
        ``short_title``, which is used by ``_load_code_aliases`` instead).
        A name that two instruments share is left out: it would link to whichever came
        first. A failing query fails the step.
        """
        index: InstrumentAliasMap = {}
        ambiguous: set[str] = set()
        rows = list(semantic_queries.instrument_alias_rows(self.store))

        for row in rows:
            bwb_id = row.get("bwb_id")
            celex = row.get("celex")
            bwb_norm = normalize_instrument_id(bwb_id)
            celex_norm = normalize_instrument_id(celex)
            pair: tuple[str | None, str | None] = (bwb_norm, celex_norm)

            for name_field in ("title", "citation_title"):
                name = row.get(name_field)
                if not name:
                    continue
                label = str(name).strip()
                if not label or label in ambiguous:
                    continue
                if index.setdefault(label, pair) != pair:
                    del index[label]
                    ambiguous.add(label)

        return index

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
        if not from_node.arango_id or not to_node.arango_id:
            return None
        return make_edge_doc(
            from_node.arango_id,
            to_node.arango_id,
            relation,
            source=source,
            confidence=confidence,
            status=status,
            meta=meta,
        )
