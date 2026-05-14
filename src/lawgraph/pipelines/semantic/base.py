from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from lawgraph.config import load_domain_config
from lawgraph.config.settings import EDGE_STATUS_CANONIEK
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, PipelineResult

logger = get_logger(__name__)

CodeMapping = dict[str, str]
InstrumentAliasMap = dict[str, tuple[str | None, str | None]]


def _sha1_edge_key(from_id: str, relation: str, to_id: str) -> str:
    """Deterministic SHA-1 edge key — identical scheme used by ArangoStore.create_edge."""
    return hashlib.sha1(f"{from_id}:{relation}:{to_id}".encode()).hexdigest()


class SemanticPipelineBase:
    """Shared base for all semantic pipelines.

    Provides domain config loading, alias resolution, and the canonical
    _create_semantic_edge() helper so subclasses only implement run().
    """

    def __init__(
        self,
        *,
        store: ArangoStore,
        domain_profile: str | None = None,
        domain_config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self._domain_profile_name = domain_profile
        self._domain_config = domain_config

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        raise NotImplementedError

    # ------------------------------------------------------------------ config

    def _load_domain_config(self) -> dict[str, Any]:
        if self._domain_config is not None:
            return self._domain_config

        if not self._domain_profile_name:
            self._domain_config = {}
            return self._domain_config

        try:
            self._domain_config = load_domain_config(self._domain_profile_name)
        except FileNotFoundError as exc:
            logger.warning(
                "Unable to load profile %s: %s",
                self._domain_profile_name,
                exc,
            )
            self._domain_config = {}

        return self._domain_config

    def _load_code_aliases(self) -> CodeMapping:
        config = self._load_domain_config()
        aliases = config.get("code_aliases", {})
        if not isinstance(aliases, dict):
            return {}
        return {str(k).strip(): str(v).strip() for k, v in aliases.items() if k and v}

    def _build_graph_instrument_index(self) -> InstrumentAliasMap:
        """Query the instruments collection to build a name → (bwb_id, celex) map.

        Only includes instruments that have a bwb_id or celex prop. Both the
        ``title`` and ``citation_title`` props are indexed as keys. First-write
        wins — if two instruments share a name, the first one encountered wins.
        Returns an empty dict if the store is unavailable.
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

    def _load_instrument_aliases(self) -> InstrumentAliasMap:
        # 1. Broad graph-derived index (first-write wins within the graph)
        merged = self._build_graph_instrument_index()

        # 2. Profile aliases override/extend the graph index
        config = self._load_domain_config()
        raw = config.get("instrument_aliases", {})
        if isinstance(raw, dict):
            profile_aliases = _parse_instrument_aliases(raw)
            merged.update(profile_aliases)  # profile takes precedence

        return merged

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
        """Upsert a semantic edge via the unified edges collection.

        Returns True if the edge was newly created, False if it already existed
        OR if a database error occurred.

        Pass ``result`` to have errors appended to ``result.errors`` instead of
        being silently swallowed.  This lets callers distinguish "0 created because
        nothing matched" from "0 created because the database was unreachable."
        """
        if not from_node.id or not to_node.id:
            return False

        edge_key = _sha1_edge_key(from_node.id, relation, to_node.id)
        edge_doc: dict[str, Any] = {
            "_key": edge_key,
            "_from": from_node.id,
            "_to": to_node.id,
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
                f"Failed to create edge {from_node.id} → {to_node.id}"
                f" ({relation}): {exc}"
            )
            logger.error(msg)
            if result is not None:
                result.add_error(msg)
            return False


def _parse_instrument_aliases(raw: dict[str, Any]) -> InstrumentAliasMap:
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
        if scalar.upper().startswith("BWBR"):
            aliases[label] = (scalar.upper(), None)
        else:
            aliases[label] = (None, scalar.upper())
    return aliases
