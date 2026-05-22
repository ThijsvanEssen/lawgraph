from __future__ import annotations

from typing import Any

from lawgraph.config.constants import BWB_ID_PREFIX, EDGE_STATUS_CANONIEK
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.db import edge_key as _sha1_edge_key
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

CodeMapping = dict[str, str]
InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


class SemanticPipelineBase(PipelineBase):
    """Shared base for all semantic pipelines.

    Provides alias resolution and edge helpers so subclasses only implement run().
    """

    _EDGE_BATCH_SIZE: int = 500

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
        aql = """
        FOR inst IN instruments
            FILTER inst.props.short_title != null
            FILTER inst.props.bwb_id != null OR inst.props.celex != null
            RETURN {
                short_title: inst.props.short_title,
                bwb_id: inst.props.bwb_id,
                celex: inst.props.celex
            }
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
        aql = """
        FOR inst IN instruments
            FILTER inst.props.bwb_id != null OR inst.props.celex != null
            RETURN {
                bwb_id: inst.props.bwb_id,
                celex: inst.props.celex,
                title: inst.props.title,
                citation_title: inst.props.citation_title
            }
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
            bwb_norm = str(bwb_id).strip().upper() if bwb_id else None
            celex_norm = str(celex).strip().upper() if celex else None
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

    def _create_semantic_edge(
        self,
        *,
        from_node: Node,
        to_node: Node,
        relation: str,
        source: str,
        confidence: float = 0.0,
        meta: dict[str, Any] | None = None,
        result: PipelineResult | None = None,
        status: str = EDGE_STATUS_CANONIEK,
    ) -> bool:
        """Upsert a single semantic edge. Returns True if newly created.

        For high-throughput pipelines prefer ``_flush_edge_batch()`` which
        amortises N individual round-trips into one AQL batch call.
        """
        if not from_node.arango_id or not to_node.arango_id:
            return False

        edge_key = _sha1_edge_key(from_node.arango_id, relation, to_node.arango_id)
        edge_doc: dict[str, Any] = {
            "_key": edge_key,
            "_from": from_node.arango_id,
            "_to": to_node.arango_id,
            "relation": relation,
            "confidence": confidence,
            "source": source,
            "status": status,
            "meta": dict(meta or {}),
        }

        try:
            _, created = self.store.insert_or_update_edge(doc=edge_doc)
            return created
        except Exception as exc:
            msg = (
                f"Failed to create edge {from_node.arango_id} → {to_node.arango_id}"
                f" ({relation}): {exc}"
            )
            logger.error(msg)
            if result is not None:
                result.add_error(msg)
            return False

    def _flush_edge_batch(
        self,
        batch: list[dict[str, Any]],
        result: PipelineResult | None = None,
    ) -> tuple[int, int]:
        """Batch-upsert a list of pre-built edge documents in one AQL call.

        Returns (created, updated). On error, logs and appends to result.errors
        but does not raise so the pipeline can continue with the next batch.

        Build edge docs with ``_make_edge_doc()`` then call this once per
        batch rather than calling ``_create_semantic_edge()`` in a tight loop.
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
        edge_key = _sha1_edge_key(from_node.arango_id, relation, to_node.arango_id)
        return {
            "_key": edge_key,
            "_from": from_node.arango_id,
            "_to": to_node.arango_id,
            "relation": relation,
            "confidence": confidence,
            "source": source,
            "status": status,
            "meta": dict(meta or {}),
        }

    @staticmethod
    def _extract_props_text(props: dict[str, Any], *keys: str) -> str | None:
        """Return the first non-empty string value found under the given keys."""
        for key in keys:
            value = props.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def _parse_instrument_aliases(raw: dict[str, Any]) -> InstrumentAliasMap:
        """Parse a dict of instrument alias entries into a normalised InstrumentAliasMap.

        Accepts values in several forms:
        - a (bwb_id, celex) tuple
        - a dict with ``bwb_id`` and/or ``celex`` keys
        - a scalar string (BWBR… → bwb_id, anything else → celex)
        """
        aliases: InstrumentAliasMap = {}
        for alias, value in raw.items():
            label = str(alias or "").strip()
            if not label:
                continue
            # Already a parsed tuple — pass through.
            if isinstance(value, tuple) and len(value) == 2:
                aliases[label] = value  # type: ignore[assignment]
                continue
            if isinstance(value, dict):
                bwb_id = value.get("bwb_id")
                celex = value.get("celex")
                aliases[label] = (
                    str(bwb_id).strip().upper() if bwb_id else None,
                    str(celex).strip().upper() if celex else None,
                )
                continue
            scalar = str(value or "").strip()
            if not scalar:
                continue
            if scalar.upper().startswith(BWB_ID_PREFIX):
                aliases[label] = (scalar.upper(), None)
            else:
                aliases[label] = (None, scalar.upper())
        return aliases
