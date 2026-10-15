"""Normalize pipeline for Dutch Verdragenbank treaties.

Treaties are stored as Instrument nodes with:
  - kind: 'multilateraalverdrag' or 'bilateraalverdrag' by the treaty type, else 'verdrag'
  - jurisdiction: 'int'
  - props.treaty_number: the official NL treaty number
  - props.date_signed / props.date_in_force
  - props.status: the Verdragenbank status (Inwerkinggetreden, Buitenwerkinggetreden, ...)

and, from the item XML of a treaty (``verdrag-xml``, ``core.verdragenbank_xml``), its
``place_signed``, ``tractatenblad``, ``parties``, ``kingdom_parts``, ``kamerstukken``,
``parent_treaties`` and ``child_treaties``, merged into the same node.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    KIND_BILATERAL_TREATY,
    KIND_MULTILATERAL_TREATY,
    KIND_TREATY,
    MAX_TITLE_CHARS,
    RAW_KIND_VERDRAGENBANK_JSON,
    RAW_KIND_VERDRAGENBANK_XML,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.core.display import shorten
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.raw_records import payload_json, payload_text
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.core.verdragenbank_xml import parse_treaty_xml
from lawgraph.db import NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)


class VerdragenbankNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalize Verdragenbank treaty records into Instrument nodes."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_VERDRAGENBANK,
            kinds=[RAW_KIND_VERDRAGENBANK_JSON, RAW_KIND_VERDRAGENBANK_XML],
            since=since,
            batch_size=1000,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The treaties. No structural edges."""
        count = 0
        writer = NodeWriter(self.store)

        for record in raw:
            if record.get("kind") == RAW_KIND_VERDRAGENBANK_XML:
                node = self._item_node(record)
                if node is not None:
                    writer.add(node)
                    count += 1
                continue
            payload = payload_json(record)
            if not payload:
                self.progress.skip("no payload", record.get("external_id"))
                continue

            uri = payload.get("uri") or ""
            external_id = (
                record.get("external_id") or uri.rstrip("/").rsplit("/", 1)[-1]
            )
            if not external_id:
                self.progress.skip("no treaty id", record.get("key"))
                continue

            title_nl = payload.get("title_nl") or ""
            title_en = payload.get("title_en") or ""
            title = title_nl or title_en or f"Verdrag {external_id}"

            treaty_number = payload.get("verdragsnummer") or ""
            treaty_type = payload.get("treaty_type") or ""
            status = payload.get("status") or ""
            date_signed = _iso_date(payload.get("date_signed"))
            date_in_force = _iso_date(payload.get("date_in_force"))

            # Derive a kind label from the type URI or text
            kind = KIND_TREATY
            type_lower = treaty_type.lower()
            if "multilateral" in type_lower or "multilateraal" in type_lower:
                kind = KIND_MULTILATERAL_TREATY
            elif "bilateral" in type_lower or "bilateraal" in type_lower:
                kind = KIND_BILATERAL_TREATY

            is_in_force = status.lower() == "inwerkinggetreden"

            display_name = (
                shorten(title, MAX_TITLE_CHARS)
                if title
                else f"Verdrag {treaty_number or external_id}"
            )

            props: dict[str, Any] = {
                "source": SOURCE_VERDRAGENBANK,
                "external_id": external_id,
                "uri": uri,
                "title": title,
                # the name a treaty is cited and sorted by: its whole title
                "citation_title": title,
                "title_nl": title_nl,
                "title_en": title_en,
                "display_name": display_name,
                "kind": kind,
                "jurisdiction": "int",
                "treaty_number": treaty_number,
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
                key=key,
                labels=["Verdrag", "NL"],
                props=props,
            )
            writer.add(node)
            count += 1

        writer.flush()

        logger.info("Verdragenbank normalize: %d treaties processed.", count)

    def _item_node(self, record: dict[str, Any]) -> Node | None:
        """The props the item XML of a treaty adds, on the node of the treaty (merged with
        those of its SRU record); None for a record without readable XML."""
        external_id = record.get("external_id")
        text = payload_text(record)
        if not external_id or not text:
            self.progress.skip("no item XML", external_id or record.get("key"))
            return None
        try:
            props = parse_treaty_xml(text)
        except ValueError as exc:
            self.progress.fail("item XML not read", f"{external_id}: {exc}")
            return None
        return Node(
            collection=COLLECTION_INSTRUMENTS,
            key=make_node_key("verdrag", external_id),
            labels=["Verdrag", "NL"],
            props=props,
        )
