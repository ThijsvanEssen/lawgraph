from __future__ import annotations

import datetime as dt
from typing import Any, Iterable, Protocol, runtime_checkable

from config.config import load_domain_config
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node

logger = get_logger(__name__)


@runtime_checkable
class NormalizePipelineProtocol(Protocol):
    """Protocol describing the normalization pipeline contract."""

    store: ArangoStore

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any: ...

    def normalize_nodes(self, raw: Any) -> Any: ...

    def build_edges(self, raw: Any, normalized: Any) -> int: ...

    def run(self, *, since: dt.datetime | None = None) -> None: ...


class NormalizePipeline(NormalizePipelineProtocol):
    """Base class for pipelines that normalize raw_sources records."""

    def __init__(
        self,
        store: ArangoStore,
        *,
        domain_profile: str | None = None,
        domain_config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self._domain_profile_name = domain_profile
        self._domain_config: dict[str, Any] | None = domain_config
        self._domain_topic_node: Node | None = None

    def fetch_raw(self, *, since: dt.datetime | None = None) -> Any:
        """Fetch raw_sources records relevant for this pipeline."""
        raise NotImplementedError

    def normalize_nodes(self, raw: Any) -> Any:
        """Turn raw data into Node objects and insert them into domain collections."""
        raise NotImplementedError

    def build_edges(self, raw: Any, normalized: Any) -> int:
        """Create edges between normalized nodes; returns number of edges created."""
        raise NotImplementedError

    def run(self, *, since: dt.datetime | None = None) -> None:
        """Orchestrate the normalization pipeline steps with logging."""
        since_desc = self._describe_since(since)
        logger.info(
            "Starting %s normalization pipeline (since=%s).",
            self.__class__.__name__,
            since_desc,
        )

        raw = self.fetch_raw(since=since)
        normalized = self.normalize_nodes(raw)
        edge_count = self.build_edges(raw, normalized)

        logger.info(
            "%s normalization pipeline created %d edges.",
            self.__class__.__name__,
            edge_count,
        )

    @staticmethod
    def _since_iso(since: dt.datetime | None) -> str | None:
        """Return UTC isoformat for since or None."""
        if since is None:
            return None

        if since.tzinfo is None:
            since = since.replace(tzinfo=dt.timezone.utc)

        iso = since.astimezone(dt.timezone.utc).isoformat()
        if iso.endswith("+00:00"):
            return iso.replace("+00:00", "Z")
        return iso

    @classmethod
    def _describe_since(cls, since: dt.datetime | None) -> str:
        """Human-friendly description of the since parameter."""
        since_iso = cls._since_iso(since)
        if since_iso is None:
            return "full history"
        return since_iso

    def _query_raw_sources(
        self,
        *,
        source: str,
        kinds: list[str],
        since: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw_sources rows for the given source/kinds (optionally filtered by since)."""
        since_iso = self._since_iso(since)
        bind_vars = {"source": source, "kinds": kinds}

        if since_iso is None:
            aql = """
            FOR r IN raw_sources
                FILTER r.source == @source
                FILTER r.kind IN @kinds
            RETURN r
            """
        else:
            aql = """
            FOR r IN raw_sources
                FILTER r.source == @source
                FILTER r.kind IN @kinds
                FILTER r.fetched_at >= @since
            RETURN r
            """
            bind_vars["since"] = since_iso

        return list(self.store.query(aql, bind_vars=bind_vars))

    @staticmethod
    def _group_by_kind(
        rows: list[dict[str, Any]],
        *,
        kinds: Iterable[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group raw_records by their kind, keeping an entry for each requested kind."""
        grouped: dict[str, list[dict[str, Any]]] = {kind: [] for kind in kinds}
        for row in rows:
            kind = row.get("kind")
            if kind in grouped:
                grouped[kind].append(row)
        return grouped

    @staticmethod
    def _payload_json(raw: dict[str, Any]) -> dict[str, Any]:
        payload = raw.get("payload_json")
        if isinstance(payload, dict):
            return payload
        return {}

    @staticmethod
    def _payload_text(raw: dict[str, Any]) -> str | None:
        payload_text = raw.get("payload_text")
        if isinstance(payload_text, str):
            return payload_text
        return None

    @staticmethod
    def _meta(raw: dict[str, Any]) -> dict[str, Any]:
        meta = raw.get("meta")
        if isinstance(meta, dict):
            return meta
        return {}

    def domain_profile(self) -> str | None:
        return self._domain_profile_name

    def _load_domain_config(self) -> dict[str, Any]:
        if self._domain_config is not None:
            return self._domain_config

        domain = self.domain_profile()
        if not domain:
            self._domain_config = {}
            return self._domain_config

        try:
            self._domain_config = load_domain_config(domain)
        except FileNotFoundError as exc:
            logger.warning("Unable to load %s config: %s", domain, exc)
            self._domain_config = {}

        return self._domain_config

    def _get_domain_topic_node(self) -> Node | None:
        if self._domain_topic_node is not None:
            return self._domain_topic_node

        config = self._load_domain_config()
        topic_data = config.get("topic", {})
        self._domain_topic_node = self._find_topic_node(
            topic_id=topic_data.get("id"),
            slug=topic_data.get("slug"),
        )
        return self._domain_topic_node

    def _find_topic_node(
        self,
        *,
        topic_id: str | None,
        slug: str | None,
    ) -> Node | None:
        if not topic_id and not slug:
            return None

        filters: list[str] = []
        bind_vars: dict[str, Any] = {}
        if topic_id:
            filters.append("doc.props.id == @topic_id")
            bind_vars["topic_id"] = topic_id
        if slug:
            filters.append("doc.props.slug == @slug")
            bind_vars["slug"] = slug

        aql = f"""
        FOR doc IN topics
            FILTER {" OR ".join(filters)}
        RETURN doc
        """
        for doc in self.store.query(aql, bind_vars=bind_vars):
            return Node.from_document("topics", doc)
        return None

    def _ensure_related_topic_edge(
        self,
        *,
        node: Node,
        topic_node: Node,
        source: str,
        meta: dict[str, Any] | None = None,
    ) -> bool:
        if node.id is None or topic_node.id is None:
            return False

        bind_vars = {
            "from_id": node.id,
            "to_id": topic_node.id,
            "relation": "RELATED_TOPIC",
        }
        aql = """
        FOR edge IN edges_semantic
            FILTER edge._from == @from_id
            FILTER edge._to == @to_id
            FILTER edge.relation == @relation
        RETURN edge
        """

        for _ in self.store.query(aql, bind_vars=bind_vars):
            return False

        edge_meta = dict(meta or {})
        edge_meta.setdefault("source", source)

        self.store.create_edge(
            from_id=node.id,
            to_id=topic_node.id,
            relation="RELATED_TOPIC",
            strict=False,
            meta=edge_meta,
        )
        return True

    @staticmethod
    def _text_contains_keywords(
        text: str | None,
        keywords: Iterable[str],
    ) -> bool:
        if not text:
            return False

        text_lower = text.lower()
        for keyword in keywords:
            lowered = keyword.lower().strip()
            if lowered and lowered in text_lower:
                return True
        return False
