from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, TypeVar

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    EDGE_STATUS_CANONIEK,
    RAW_KIND_RS_CONTENT,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.aliases import InstrumentAliasMap, normalize_instrument_id
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.core.progress import Progress
from lawgraph.db import make_edge_doc
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


def slim(var: str, *fields: str) -> str:
    """AQL for the document *var* with only *fields* of its props.

    A judgment carries its XML, its text and its paragraphs, a TK document the whole API
    payload; a pipeline that reads one of them must not have the rest sent over. The result
    has the shape of a document, so ``Node.from_document`` reads it.
    """
    names = ", ".join(f'"{field}"' for field in fields)
    return (
        f"{{_key: {var}._key, type: {var}.type, labels: {var}.labels, "
        f"props: KEEP({var}.props, {names})}}"
    )


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
        since_filter = "FILTER r.fetched_at >= @since" if since_iso else ""
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            {since_filter}
            FILTER r.payload_ref != null
            RETURN {{ecli: r.meta.ecli || r.external_id, payload_ref: r.payload_ref}}
        """
        bind: dict[str, Any] = {
            "source": SOURCE_RECHTSPRAAK,
            "kind": RAW_KIND_RS_CONTENT,
        }
        if since_iso:
            bind["since"] = since_iso
        total = None
        if (
            not since_iso
        ):  # from the index; with a date every record would have to be read
            count_aql = f"""
            FOR r IN {COLLECTION_RAW_SOURCES}
                FILTER r.source == @source AND r.kind == @kind
                COLLECT WITH COUNT INTO n
                RETURN n
            """
            count = next(iter(self.store.query(count_aql, bind)), None)
            total = count if isinstance(count, int) else None
        rows = self.store.query(aql, bind, batch_size=JUDGMENT_BATCH_SIZE)
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
        bind: dict[str, Any] = {"source": SOURCE_RECHTSPRAAK}
        recent = ""
        if since_iso:
            bind["eclis"] = self._recent_eclis(since_iso)
            recent = "FILTER j.props.ecli IN @eclis"
        aql = f"""
        FOR j IN {COLLECTION_JUDGMENTS}
            FILTER j.props.source == @source
            {recent}
            RETURN {slim("j", "ecli", "paragraphs")}
        """
        total = None
        if not since_iso:  # from the index; with a date every judgment would be read
            count_aql = f"""
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER j.props.source == @source
                COLLECT WITH COUNT INTO n
                RETURN n
            """
            count = next(iter(self.store.query(count_aql, bind)), None)
            total = count if isinstance(count, int) else None
        rows = self.store.query(aql, bind, batch_size=JUDGMENT_BATCH_SIZE)
        for row in self._track(rows, "judgments", total=total):
            node = Node.from_document(COLLECTION_JUDGMENTS, row)
            paragraphs = node.props.get("paragraphs")
            if paragraphs:
                yield node, paragraphs

    def _recent_eclis(self, since_iso: str) -> list[str]:
        """The ECLIs of the judgments retrieved at or after *since_iso*."""
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            FILTER r.fetched_at >= @since
            RETURN r.meta.ecli || r.external_id
        """
        bind = {
            "source": SOURCE_RECHTSPRAAK,
            "kind": RAW_KIND_RS_CONTENT,
            "since": since_iso,
        }
        return sorted({str(e) for e in self.store.query(aql, bind) if e})

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
        aql = f"""
        FOR doc IN {COLLECTION_JUDGMENTS}
            FILTER doc.props.ecli IN @eclis
            RETURN {{ ecli: doc.props.ecli, id: doc._id }}
        """
        by_ecli: dict[str, str] = {}
        for row in self.store.query(aql, bind_vars={"eclis": sorted(eclis)}):
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

    def _load_alias_index(
        self, aql: str, key_field: str, value_fields: tuple[str, ...]
    ) -> dict[str, str]:
        """Build a normalised key → value alias mapping from an AQL query.

        For each row returned by *aql*, the value at *key_field* becomes the
        dict key. The first non-empty value found across *value_fields* (in
        order) becomes the dict value. First-write-wins — subsequent rows that
        produce the same key are ignored. Keys and values are stripped.
        A failing query fails the step: without the names every citation would be missed.
        """
        index: dict[str, str] = {}
        for row in self.store.query(aql):
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
        aql = f"""
        FOR inst IN {COLLECTION_INSTRUMENTS}
            FILTER inst.props.short_title != null
            FILTER inst.props.bwb_id != null OR inst.props.celex != null
            RETURN {{
                short_title: inst.props.short_title,
                bwb_id: inst.props.bwb_id,
                celex: inst.props.celex
            }}
        """
        return self._load_alias_index(aql, "short_title", ("bwb_id", "celex"))

    def _load_instrument_aliases(self) -> InstrumentAliasMap:
        """Query the instruments collection to build a name → (bwb_id, celex) map.

        Only includes instruments that have a bwb_id or celex prop. The
        ``title`` and ``citation_title`` props are indexed as keys (not
        ``short_title``, which is used by ``_load_code_aliases`` instead).
        A name that two instruments share is left out: it would link to whichever came
        first. A failing query fails the step.
        """
        aql = f"""
        FOR inst IN {COLLECTION_INSTRUMENTS}
            FILTER inst.props.bwb_id != null OR inst.props.celex != null
            RETURN {{
                bwb_id: inst.props.bwb_id,
                celex: inst.props.celex,
                title: inst.props.title,
                citation_title: inst.props.citation_title
            }}
        """
        index: InstrumentAliasMap = {}
        ambiguous: set[str] = set()
        rows = list(self.store.query(aql))

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
