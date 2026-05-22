"""Normalize pipeline for Eerste Kamer Kamerstukken and stemmingen."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_PUBLICATIONS,
    COLLECTION_STEMMINGEN,
    RAW_KIND_EK_STUK,
    RELATION_BESLUIT,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)


class EerstekamerNormalizePipeline(NormalizePipeline):
    """Normalize EK Kamerstukken into Publication nodes and stemmingen into Stemming nodes."""

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
        stemmingen = 0

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
                node = self._normalize_stemming(record, payload, result)
                if node:
                    stemmingen += 1
                    result.created += 1
                    item_id = str(payload.get("Id") or "")
                    nodes[f"stemming:{item_id}"] = node
            else:
                node = self._normalize_kamerstuk(record, payload, result)
                if node:
                    item_id = str(payload.get("Id") or "")
                    nodes[item_id] = node
                    result.created += 1

        logger.info(
            "EK normalize: %d publications, %d stemmingen processed.",
            len(nodes),
            stemmingen,
        )
        return nodes

    def _normalize_kamerstuk(
        self, record: dict[str, Any], payload: dict[str, Any], result: PipelineResult
    ) -> Node | None:
        item_id = str(payload.get("Id") or "")
        if not item_id:
            result.skipped += 1
            return None

        nummer = payload.get("Nummer") or ""
        soort = payload.get("Soort") or ""
        titel = payload.get("Titel") or f"EK {soort} {nummer}"
        datum = _iso_date(payload.get("Datum"))
        vergaderjaar = payload.get("Vergaderjaar") or ""
        dossier_nummer = payload.get("DossierNummer")

        display_name = titel[:200] if titel else f"EK-stuk {nummer}"

        props: dict[str, Any] = {
            "source": SOURCE_EERSTEKAMER,
            "external_id": item_id,
            "soort": soort,
            "nummer": nummer,
            "titel": titel,
            "datum": datum,
            "vergaderjaar": vergaderjaar,
            "display_name": display_name,
        }
        if dossier_nummer:
            props["dossier_nummer"] = str(dossier_nummer)

        key = make_node_key("ek", item_id)
        node = Node(
            collection=COLLECTION_PUBLICATIONS,
            type=NodeType.PUBLICATION,
            key=key,
            labels=["EersteKamer", "EK"],
            props=props,
        )
        return self.store.insert_or_update(node)

    def _normalize_stemming(
        self, record: dict[str, Any], payload: dict[str, Any], result: PipelineResult
    ) -> Node | None:
        item_id = str(payload.get("Id") or "")
        if not item_id:
            result.skipped += 1
            return None

        kamerstuk_id = str(payload.get("KamerstukId") or "")
        vergadering_id = str(payload.get("VergaderingId") or "")
        soort = payload.get("Soort") or ""
        aangenomen_raw = payload.get("Aangenomen")

        # OData: true/false, int 0/1, or "Aangenomen"/"Verworpen" string
        if isinstance(aangenomen_raw, bool):
            aangenomen = aangenomen_raw
        elif isinstance(aangenomen_raw, int):
            aangenomen = bool(aangenomen_raw)
        elif isinstance(aangenomen_raw, str):
            aangenomen = aangenomen_raw.lower() in ("true", "aangenomen", "ja")
        else:
            aangenomen = None

        meta = self._meta(record)
        datum = _iso_date(meta.get("datum") or payload.get("Datum"))

        display_name = f"EK stemming {soort}" if soort else f"EK stemming {item_id}"
        if aangenomen is True:
            display_name += " (aangenomen)"
        elif aangenomen is False:
            display_name += " (verworpen)"

        props: dict[str, Any] = {
            "source": SOURCE_EERSTEKAMER,
            "external_id": item_id,
            "soort": soort,
            "kamerstuk_id": kamerstuk_id,
            "vergadering_id": vergadering_id,
            "aangenomen": aangenomen,
            "datum": datum,
            "display_name": display_name,
            "chamber": "EK",
        }

        key = make_node_key("ek", "stemming", item_id)
        node = Node(
            collection=COLLECTION_STEMMINGEN,
            type=NodeType.STEMMING,
            key=key,
            labels=["EersteKamer", "EK"],
            props=props,
        )
        return self.store.insert_or_update(node)

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> int:
        edges = 0
        for _key, node in normalized.items():
            if node.collection != COLLECTION_STEMMINGEN:
                continue
            if node.arango_id is None:
                continue
            kamerstuk_id = str(node.props.get("kamerstuk_id") or "")
            if not kamerstuk_id:
                continue
            kamerstuk_key = make_node_key("ek", kamerstuk_id)
            kamerstuk_arangoid = f"{COLLECTION_PUBLICATIONS}/{kamerstuk_key}"
            try:
                self.store.create_edge(
                    from_id=node.arango_id,
                    to_id=kamerstuk_arangoid,
                    relation=RELATION_BESLUIT,
                    source=SOURCE_EERSTEKAMER,
                )
                edges += 1
            except Exception as exc:
                logger.error(
                    "EK edge creation failed %s → %s: %s",
                    node.arango_id,
                    kamerstuk_arangoid,
                    exc,
                )
        return edges
