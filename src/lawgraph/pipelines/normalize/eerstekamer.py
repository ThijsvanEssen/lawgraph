"""Normalize pipeline for Eerste Kamer Kamerstukken and Stemmingen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    MAX_TITLE_CHARS,
    RAW_KIND_EK_STUK,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class EerstekamerNormalizePipeline(NormalizePipelineBase):
    """Normalize EK Kamerstukken into documents and EK Stemmingen into decisions."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EK_STUK],
            since=since,
        )
        logger.info("Loaded %d EK raw_sources.", len(rows))
        return rows

    def normalize_nodes(
        self, raw: list[dict[str, Any]], result: PipelineResult
    ) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        decisions = 0

        for record in raw:
            payload = self._payload_json(record)
            if not payload or not isinstance(payload, dict):
                result.skipped += 1
                continue

            # Detect record type: authoritative discriminator is meta.record_type;
            # fall back to payload-field heuristic for older records.
            meta = self._meta(record)
            record_type = meta.get("record_type")
            if not record_type:
                record_type = (
                    "stemming"
                    if "KamerstukId" in payload and "Aangenomen" in payload
                    else "kamerstuk"
                )

            if record_type == "stemming":
                node = self._normalize_decision(record, payload, result)
                if node:
                    decisions += 1
                    item_id = str(payload.get("Id") or "")
                    nodes[f"stemming:{item_id}"] = node
            else:
                node = self._normalize_paper(record, payload, result)
                if node:
                    item_id = str(payload.get("Id") or "")
                    nodes[item_id] = node

        logger.info(
            "EK normalize: %d publications, %d decisions processed.",
            len(nodes),
            decisions,
        )
        return nodes

    def _normalize_paper(
        self, record: dict[str, Any], payload: dict[str, Any], result: PipelineResult
    ) -> Node | None:
        item_id = str(payload.get("Id") or "")
        if not item_id:
            result.skipped += 1
            return None

        number = payload.get("Nummer") or ""
        kind = payload.get("Soort") or ""
        title = payload.get("Titel") or f"EK {kind} {number}"
        date = _iso_date(payload.get("Datum"))
        session_year = payload.get("Vergaderjaar") or ""
        dossier_number = payload.get("DossierNummer")

        display_name = title[:MAX_TITLE_CHARS] if title else f"EK-stuk {number}"

        props: dict[str, Any] = {
            "source": SOURCE_EERSTEKAMER,
            "external_id": item_id,
            "kind": kind,
            "number": number,
            "title": title,
            "date": date,
            "session_year": session_year,
            "display_name": display_name,
        }
        if dossier_number:
            props["dossier_number"] = str(dossier_number)

        key = make_node_key("ek", item_id)
        node = Node(
            collection=COLLECTION_DOCUMENTS,
            type=NodeType.DOCUMENT,
            key=key,
            labels=["EersteKamer", "EK"],
            props=props,
        )
        stored, _ = self.store.insert_or_update(node)
        return stored

    def _normalize_decision(
        self, record: dict[str, Any], payload: dict[str, Any], result: PipelineResult
    ) -> Node | None:
        item_id = str(payload.get("Id") or "")
        if not item_id:
            result.skipped += 1
            return None

        parliamentary_paper_id = str(payload.get("KamerstukId") or "")
        meeting_id = str(payload.get("VergaderingId") or "")
        kind = payload.get("Soort") or ""
        passed_raw = payload.get("Aangenomen")

        # OData: true/false, int 0/1, or "Aangenomen"/"Verworpen" string
        if isinstance(passed_raw, bool):
            passed = passed_raw
        elif isinstance(passed_raw, int):
            passed = bool(passed_raw)
        elif isinstance(passed_raw, str):
            passed = passed_raw.lower() in ("true", "aangenomen", "ja")
        else:
            passed = None

        meta = self._meta(record)
        date = _iso_date(meta.get("date") or payload.get("Datum"))

        display_name = f"EK stemming {kind}" if kind else f"EK stemming {item_id}"
        if passed is True:
            display_name += " (aangenomen)"
        elif passed is False:
            display_name += " (verworpen)"

        props: dict[str, Any] = {
            "source": SOURCE_EERSTEKAMER,
            "external_id": item_id,
            "kind": kind,
            "parliamentary_paper_id": parliamentary_paper_id,
            "meeting_id": meeting_id,
            "passed": passed,
            "date": date,
            "display_name": display_name,
            "chamber": "EK",
        }

        key = make_node_key("ek", "stemming", item_id)
        node = Node(
            collection=COLLECTION_DECISIONS,
            type=NodeType.DECISION,
            key=key,
            labels=["EersteKamer", "EK"],
            props=props,
        )
        stored, _ = self.store.insert_or_update(node)
        return stored

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> None:
        """None. EK stukken reach the graph through their TK dossier.

        The link is made by ``EerstekamerDossierLinkSemanticPipeline``, which
        matches ``DossierNummer`` against the TK kamerstukdossiers.
        """
