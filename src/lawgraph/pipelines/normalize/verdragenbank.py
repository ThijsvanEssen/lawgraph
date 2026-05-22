"""Normalize pipeline for Dutch Verdragenbank treaties.

Treaties are stored as Instrument nodes with:
  - kind: 'verdrag' (bilateral) or 'multilateraalverdrag'
  - jurisdiction: 'nl' (NL is party) or 'int' for purely international
  - props.verdragsnummer: the official NL treaty number
  - props.date_signed / props.date_in_force
  - props.status: 'in force' / 'not in force' / etc.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    RAW_KIND_VERDRAG,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)


class VerdragenbankNormalizePipeline(NormalizePipeline):
    """Normalize Verdragenbank treaty records into Instrument nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_VERDRAGENBANK,
            kinds=[RAW_KIND_VERDRAG],
            since=since,
        )
        logger.info("Loaded %d Verdragenbank raw_sources.", len(rows))
        return rows

    def normalize_nodes(self, raw: list[dict[str, Any]], result: PipelineResult) -> dict[str, Node]:
        nodes: dict[str, Node] = {}

        for record in raw:
            payload = self._payload_json(record)
            if not payload or not isinstance(payload, dict):
                result.skipped += 1
                continue

            uri = payload.get("uri") or ""
            external_id = (
                record.get("external_id") or uri.rstrip("/").rsplit("/", 1)[-1]
            )
            if not external_id:
                result.skipped += 1
                continue

            title_nl = payload.get("title_nl") or ""
            title_en = payload.get("title_en") or ""
            title = title_nl or title_en or f"Verdrag {external_id}"

            verdragsnummer = payload.get("verdragsnummer") or ""
            treaty_type = payload.get("treaty_type") or ""
            status = payload.get("status") or ""
            date_signed = _iso_date(payload.get("date_signed"))
            date_in_force = _iso_date(payload.get("date_in_force"))

            # Derive a kind label from the type URI or text
            kind = "verdrag"
            type_lower = treaty_type.lower()
            if "multilateral" in type_lower or "multilateraal" in type_lower:
                kind = "multilateraalverdrag"
            elif "bilateral" in type_lower or "bilateraal" in type_lower:
                kind = "bilateraalverdrag"

            is_in_force = "force" in status.lower() and "not" not in status.lower()

            display_name = (
                title[:200] if title else f"Verdrag {verdragsnummer or external_id}"
            )

            props: dict[str, Any] = {
                "source": SOURCE_VERDRAGENBANK,
                "external_id": external_id,
                "uri": uri,
                "title": title,
                "title_nl": title_nl,
                "title_en": title_en,
                "display_name": display_name,
                "kind": kind,
                "jurisdiction": "int",
                "verdragsnummer": verdragsnummer,
                "treaty_type": treaty_type,
                "status": status,
                "in_force": is_in_force,
            }
            if date_signed:
                props["date_signed"] = date_signed
            if date_in_force:
                props["date_in_force"] = date_in_force

            key = make_node_key("verdrag", external_id)
            node = Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=key,
                labels=["Verdrag", "NL"],
                props=props,
            )
            node = self.store.insert_or_update(node)
            nodes[external_id] = node
            result.created += 1

        logger.info("Verdragenbank normalize: %d treaties processed.", len(nodes))
        return nodes

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> int:
        return 0
