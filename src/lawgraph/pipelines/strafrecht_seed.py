from __future__ import annotations

from typing import Any

from lawgraph.config import load_strafrecht_config
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType

logger = get_logger(__name__)


class StrafrechtSeedPipeline:
    """Seed the strafrecht topic, instruments, and related edges from config."""

    def __init__(
        self,
        *,
        store: ArangoStore,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.config = config or load_strafrecht_config()
        self.topic_node: Node | None = None

    def run(self) -> dict[str, int]:
        summary = {
            "topic_created": 0,
            "topic_updated": 0,
            "instruments_created": 0,
            "instruments_updated": 0,
            "related_edges_created": 0,
        }

        topic_node, topic_created = self._ensure_topic_node()
        self.topic_node = topic_node
        summary["topic_created" if topic_created else "topic_updated"] = 1

        instrument_entries = []
        instrument_entries.extend(self.config.get("nl_instruments", []))
        instrument_entries.extend(self.config.get("eu_instruments", []))

        for entry in instrument_entries:
            instrument_node, instrument_created = self._ensure_instrument(entry)
            if instrument_created:
                summary["instruments_created"] += 1
            else:
                summary["instruments_updated"] += 1

            if topic_node:
                edge_created = self._ensure_related_topic_edge(
                    from_node=instrument_node,
                    to_topic_node=topic_node,
                    config_id=entry.get("id"),
                )
                if edge_created:
                    summary["related_edges_created"] += 1

        logger.info(
            "Strafrecht seed completed: %s",
            summary,
        )
        return summary

    def _ensure_topic_node(self) -> tuple[Node, bool]:
        topic_data = self.config.get("topic", {})
        topic_id = topic_data.get("id")
        slug = topic_data.get("slug")
        if not topic_id or not slug:
            raise ValueError("Strafrecht topic configuration must include id and slug.")

        props: dict[str, Any] = {}
        if topic_id:
            props["id"] = topic_id
        if slug:
            props["slug"] = slug
        if topic_data.get("name"):
            props["name"] = topic_data["name"]
        if topic_data.get("description"):
            props["description"] = topic_data["description"]
        if topic_data.get("tags"):
            props["tags"] = list(topic_data["tags"])

        labels = list(topic_data.get("labels", []))
        if "Domain" not in labels:
            labels.append("Domain")

        existing_node = self._find_topic_node(topic_id=topic_id, slug=slug)
        node = Node(
            collection="topics",
            type=NodeType.TOPIC,
            key=existing_node.key if existing_node else None,
            labels=labels,
            props=props,
        )

        if existing_node:
            self.store.update_node(node)
            return node, False

        inserted = self.store.insert_node(node)
        return inserted, True

    def _ensure_instrument(
        self,
        entry: dict[str, Any],
    ) -> tuple[Node, bool]:
        config_id = entry.get("id")
        if not config_id:
            raise ValueError("Instrument entry must include an id.")

        labels = list(entry.get("labels", []))
        if "Strafrecht" not in labels:
            labels.append("Strafrecht")

        props: dict[str, Any] = {"config_id": config_id}
        for property_name in ("jurisdiction", "kind", "title", "short_title", "notes"):
            property_value = entry.get(property_name)
            if property_value:
                props[property_name] = property_value

        if entry.get("bwb_id"):
            props["bwb_id"] = entry["bwb_id"]
        if entry.get("celex"):
            props["celex"] = entry["celex"]
        if entry.get("topics"):
            props["topics"] = list(entry["topics"])

        existing_node = self._find_instrument_by_config_id(config_id)
        node = Node(
            collection="instruments",
            type=NodeType.INSTRUMENT,
            key=existing_node.key if existing_node else None,
            labels=labels,
            props=props,
        )

        if existing_node:
            self.store.update_node(node)
            return node, False

        inserted = self.store.insert_node(node)
        return inserted, True

    def _ensure_related_topic_edge(
        self,
        *,
        from_node: Node,
        to_topic_node: Node,
        config_id: str | None,
    ) -> bool:
        if from_node.id is None or to_topic_node.id is None:
            return False

        bind_vars = {
            "from_id": from_node.id,
            "to_id": to_topic_node.id,
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

        meta = {
            "source": "config/strafrecht.yml",
        }
        if config_id:
            meta["config_id"] = config_id

        self.store.create_edge(
            from_id=from_node.id,
            to_id=to_topic_node.id,
            relation="RELATED_TOPIC",
            strict=False,
            meta=meta,
        )
        return True

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

    def _find_instrument_by_config_id(self, config_id: str) -> Node | None:
        aql = """
        FOR doc IN instruments
            FILTER doc.props.config_id == @config_id
        RETURN doc
        """
        bind_vars = {"config_id": config_id}
        for doc in self.store.query(aql, bind_vars=bind_vars):
            return Node.from_document("instruments", doc)
        return None
