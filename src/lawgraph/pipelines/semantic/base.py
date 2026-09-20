from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_CANONIEK,
)
from lawgraph.core.aliases import InstrumentAliasMap, normalize_instrument_id
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import make_edge_doc
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

CodeMapping = dict[str, str]


def _skeleton(node: Node) -> Node:
    return Node(
        collection=node.collection,
        type=node.type,
        key=node.key,
        props={},
        _skip_validation=True,
    )


class SemanticPipelineBase(PipelineBase):
    """Shared base for all semantic pipelines.

    Provides alias resolution and edge helpers so subclasses only implement run().
    """

    _EDGE_BATCH_SIZE: int = 500

    def __init__(self, store: Any) -> None:
        super().__init__(store=store)
        # (collection, key) -> lightweight Node, or None when known to be absent.
        self._node_cache: dict[tuple[str, str], Node | None] = {}

    # ------------------------------------------------------------ node lookup

    def _lookup_node(self, collection: str, key: str) -> Node | None:
        """``get_node`` with a per-run cache of hits *and* misses.

        Citation targets repeat a lot ("artikel 1", "art. 287 Sr"), so this turns
        one lookup per citation into one per distinct target. The returned node
        is a skeleton (key/collection/type, no props): use it as an edge endpoint,
        not to read data. Call ``_remember_node`` after creating a stub, and
        ``_prefetch_nodes`` to fill the cache for a whole batch in one query.
        """
        cache_key = (collection, key)
        if cache_key not in self._node_cache:
            node = self.store.get_node(collection, key)
            self._node_cache[cache_key] = None if node is None else _skeleton(node)
        return self._node_cache[cache_key]

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
        Returns an empty dict if the store is unavailable.
        """
        index: dict[str, str] = {}
        try:
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
        except Exception as exc:
            logger.debug("Alias index query unavailable: %s", exc)
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
        First-write wins — if two instruments share a name, the first one
        encountered wins. Returns an empty dict if the store is unavailable.
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
        try:
            rows = list(self.store.query(aql))
        except Exception as exc:
            logger.debug("Graph instrument index unavailable: %s", exc)
            return index

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
                if label and label not in index:
                    index[label] = pair

        return index

    # ------------------------------------------------------------------ edges

    def _flush_edge_batch(
        self,
        batch: list[dict[str, Any]],
        result: PipelineResult | None = None,
    ) -> tuple[int, int]:
        """Batch-upsert a list of pre-built edge documents in one AQL call.

        Returns (created, updated). On error, logs and appends to result.errors
        but does not raise so the pipeline can continue with the next batch.

        Build edge docs with ``_make_edge_doc()`` and add them with
        ``_queue_edge()``, which calls this once per full batch.
        """
        if not batch:
            return 0, 0
        try:
            created, updated = self.store.bulk_insert_or_update_edges(batch)
            return created, updated
        except Exception as exc:
            msg = f"Batch edge upsert failed ({len(batch)} docs): {exc}"
            logger.error(msg)
            if result is not None:
                result.add_error(msg)
            return 0, 0

    def _queue_edge(
        self,
        batch: list[dict[str, Any]],
        doc: dict[str, Any] | None,
        result: PipelineResult,
    ) -> None:
        """Append *doc* to *batch* (None is skipped); write the batch when full."""
        if doc is None:
            return
        batch.append(doc)
        if len(batch) >= self._EDGE_BATCH_SIZE:
            self._write_batch(batch, result)

    def _write_batch(self, batch: list[dict[str, Any]], result: PipelineResult) -> None:
        """Bulk-write *batch*, tally created/updated on *result*, and empty it."""
        created, updated = self._flush_edge_batch(batch, result)
        result.created += created
        result.updated += updated
        batch.clear()

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
