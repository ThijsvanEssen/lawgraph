"""Normalize TK Zaak records into cases.

Every Zaak the Tweede Kamer handles becomes a Case — no filtering by kind;
what a case is about is the ``kind`` the source gives it. The documents of a
case are written by ``tk_cases``, which also draws the PART_OF edges to the
cases and dossiers they name.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import COLLECTION_CASES, RAW_KIND_TK_ZAAK, SOURCE_TK
from lawgraph.core import tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.values import first_str
from lawgraph.db import NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class TKNormalizePipeline(NormalizePipelineBase):
    """Turn raw TK Zaak records into cases."""

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch the TK Zaak raw records to normalize."""
        kinds = [RAW_KIND_TK_ZAAK]
        rows = self._query_raw_sources(source=SOURCE_TK, kinds=kinds, since=since)
        grouped = self._group_by_kind(rows, kinds=kinds)

        cases = grouped[RAW_KIND_TK_ZAAK]
        logger.info("Loaded %d TK Zaak raw records.", len(cases))
        return {"cases": cases}

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Translate the raw TK payloads into case nodes."""
        return {"cases": self._normalize_cases(raw["cases"])}

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """None: a case is linked to its dossiers once the dossiers exist."""
        return 0

    def _normalize_cases(self, raw_records: list[dict[str, Any]]) -> dict[str, Node]:
        """Case nodes, keyed by the Zaak identifier documents refer to."""
        nodes: dict[str, Node] = {}
        for raw in raw_records:
            payload = self._payload_json(raw)
            external_id = first_str(
                [payload.get("Id"), payload.get("ZaakId"), payload.get("ZaakNummer")],
                skip_blank=True,
            )
            if external_id is None:
                logger.warning(
                    "Skipping a TK Zaak without an identifier (_key=%s).",
                    raw.get("_key"),
                )
                continue

            title = (
                payload.get("Titel")
                or payload.get("ZaakTitel")
                or payload.get("Onderwerp")
            )
            props: dict[str, Any] = {
                "source": SOURCE_TK,
                "external_id": external_id,
                "raw": payload,
                "number": str(payload.get("Nummer") or payload.get("ZaakNummer") or ""),
                # The dossiers this case belongs to; the dossier pipeline turns
                # them into PART_OF edges once the dossier nodes exist.
                "dossier_numbers": tk_records.dossier_numbers([payload]),
            }
            if title:
                props["title"] = title
            if payload.get("Citeertitel"):
                props["citation_title"] = payload["Citeertitel"]
            props["display_name"] = props.get("title") or f"Zaak {external_id}"

            nodes[external_id] = Node(
                collection=COLLECTION_CASES,
                type=NodeType.CASE,
                key=make_node_key(external_id),
                labels=["TK"],
                props=props,
            )

        with NodeWriter(self.store) as writer:
            writer.add_all(nodes.values())
        logger.info("Normalized %d TK cases.", len(nodes))
        return nodes
