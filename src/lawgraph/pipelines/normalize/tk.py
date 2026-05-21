from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
    RAW_KIND_TK_DOCUMENTVERSIE,
    RAW_KIND_TK_ZAAK,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF_PROCEDURE,
    SOURCE_TK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db import _edge_key as _sha1_edge_key
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)


class TkNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns TK raw dumps into domain nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch TK Zaak and DocumentVersie raw records for normalization."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_TK])
        rows = self._query_raw_sources(source=SOURCE_TK, kinds=kinds, since=since)
        grouped = self._group_by_kind(rows, kinds=kinds)

        raw_zaken = grouped.get(RAW_KIND_TK_ZAAK, [])
        raw_docs = grouped.get(RAW_KIND_TK_DOCUMENTVERSIE, [])

        logger.info(
            "Loaded %d TK Zaak records and %d TK DocumentVersie records from raw_sources.",
            len(raw_zaken),
            len(raw_docs),
        )

        return {"zaken": raw_zaken, "documentversies": raw_docs}

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Translate raw TK payloads into procedure and publication nodes."""
        raw_zaken = raw.get("zaken", [])
        raw_docs = raw.get("documentversies", [])

        procedures_by_external_id = self._normalize_procedures(raw_zaken)
        publications = self._normalize_publications(raw_docs)

        return {
            "procedures_by_external_id": procedures_by_external_id,
            "publications": publications,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """Create PART_OF_PROCEDURE edges."""
        procedures_by_external_id: dict[str, Node] = normalized[
            "procedures_by_external_id"
        ]
        publications: list[Node] = normalized["publications"]

        raw_docs = raw.get("documentversies", [])
        logger.debug(
            "Linking %d TK DocumentVersie records to procedures.",
            len(raw_docs),
        )

        edge_docs: list[dict[str, Any]] = []
        for publication in publications:
            procedure_external_id = publication.props.get("procedure_external_id")
            if not procedure_external_id:
                continue

            procedure_node = procedures_by_external_id.get(procedure_external_id)
            if not procedure_node or not procedure_node.id or not publication.id:
                logger.warning(
                    "Cannot link publication %s to procedure %s (missing node).",
                    publication.props.get("external_id"),
                    procedure_external_id,
                )
                continue

            edge_key = _sha1_edge_key(
                publication.id, RELATION_PART_OF_PROCEDURE, procedure_node.id
            )
            edge_docs.append(
                {
                    "_key": edge_key,
                    "_from": publication.id,
                    "_to": procedure_node.id,
                    "relation": RELATION_PART_OF_PROCEDURE,
                    "source": "tk-documentversie",
                    "status": "canoniek",
                    "meta": {},
                }
            )

        edge_count = 0
        _EDGE_BATCH = 500
        for batch_start in range(0, len(edge_docs), _EDGE_BATCH):
            batch = edge_docs[batch_start : batch_start + _EDGE_BATCH]
            try:
                created, _ = self.store.bulk_insert_or_update_edges(batch)
                edge_count += created
            except Exception as exc:  # pragma: no cover - logging only
                logger.error("TK edge batch upsert failed: %s", exc)

        logger.info(
            "TK normalization: %d procedures, %d publications, %d edges.",
            len(procedures_by_external_id),
            len(publications),
            edge_count,
        )

        return edge_count

    _NODE_BATCH_SIZE = 200

    def _normalize_procedures(
        self,
        raw_zaken: list[dict[str, Any]],
    ) -> dict[str, Node]:
        procedures_by_external_id: dict[str, Node] = {}
        pending_docs: list[dict[str, Any]] = []
        pending_nodes: list[Node] = []

        for raw in raw_zaken:
            payload = self._payload_json(raw)
            candidates = [
                payload.get("Id"),
                payload.get("ZaakId"),
                payload.get("ZaakNummer"),
            ]
            external_id = self._first_non_empty(candidates)

            if external_id is None:
                logger.warning(
                    "Skipping TK Zaak without identifiable external_id (_key=%s).",
                    raw.get("_key"),
                )
                continue

            title_value = (
                payload.get("Titel")
                or payload.get("ZaakTitel")
                or payload.get("Omschrijving")
            )
            citeertitel = payload.get("Citeertitel")

            props: dict[str, Any] = {
                "source": SOURCE_TK,
                "external_id": external_id,
                "raw": payload,
            }

            if title_value:
                props["title"] = title_value
            if citeertitel:
                props["citation_title"] = citeertitel

            # Store kamerstuknummer so TkDossiersNormalizePipeline._link_zaken_to_dossiers
            # can create DEEL_VAN_DOSSIER edges between procedures and kamerstukdossiers.
            zaak_nummer = payload.get("Nummer") or payload.get("ZaakNummer")
            if zaak_nummer:
                props["kamerstuknummer"] = str(zaak_nummer)

            props["display_name"] = props.get("title") or f"Procedure {external_id}"
            key = make_node_key(external_id)

            node = Node(
                collection=COLLECTION_PROCEDURES,
                type=NodeType.PROCEDURE,
                key=key,
                labels=["TK"],
                props=props,
            )

            pending_docs.append(node.to_document())
            pending_nodes.append(node)

        # Batch-upsert all procedure nodes.
        for batch_start in range(0, len(pending_docs), self._NODE_BATCH_SIZE):
            self.store.bulk_insert_or_update_nodes(
                COLLECTION_PROCEDURES,
                pending_docs[batch_start : batch_start + self._NODE_BATCH_SIZE],
            )

        for node in pending_nodes:
            if node.props.get("external_id"):
                procedures_by_external_id[node.props["external_id"]] = node

        logger.info(
            "Normalized %d TK procedures into nodes.",
            len(procedures_by_external_id),
        )

        return procedures_by_external_id

    def _normalize_publications(
        self,
        raw_docs: list[dict[str, Any]],
    ) -> list[Node]:
        publications: list[Node] = []
        pending_docs: list[dict[str, Any]] = []

        for raw in raw_docs:
            payload = self._payload_json(raw)
            candidates = [
                payload.get("Id"),
                payload.get("DocumentVersieId"),
            ]
            external_id = self._first_non_empty(candidates)

            if external_id is None:
                logger.warning(
                    "Skipping TK DocumentVersie without external_id (_key=%s).",
                    raw.get("_key"),
                )
                continue

            # Payload is a Document record with an optional expanded Zaak list.
            zaak_list = payload.get("Zaak")
            zaak = (
                zaak_list[0] if isinstance(zaak_list, list) and zaak_list else None
            ) or {}
            procedure_external_id = self._first_non_empty(
                [
                    zaak.get("Id"),
                    zaak.get("Nummer"),
                    payload.get("ZaakId"),
                    payload.get("ZaakNummer"),
                ]
            )

            props: dict[str, Any] = {
                "source": SOURCE_TK,
                "external_id": external_id,
                "raw": payload,
            }
            if procedure_external_id:
                props["procedure_external_id"] = procedure_external_id

            title_value = (
                payload.get("Titel")
                or payload.get("TitelMetBijlagen")
                or payload.get("Onderwerp")
            )
            citeertitel = payload.get("Citeertitel")
            document_number = payload.get("DocumentNummer")
            onderwerp = payload.get("Onderwerp")

            if title_value:
                props["title"] = title_value
            if citeertitel:
                props["citation_title"] = citeertitel
            if document_number:
                props["document_number"] = document_number
            if onderwerp:
                props["onderwerp"] = onderwerp
            if payload.get("Soort"):
                props["soort"] = payload["Soort"]

            title = props.get("title")
            doc_num = props.get("document_number")
            props["display_name"] = (
                f"{title} ({doc_num})"
                if title and doc_num
                else title or props.get("soort") or "Publicatie"
            )
            key = make_node_key(external_id)

            node = Node(
                collection=COLLECTION_PUBLICATIONS,
                type=NodeType.PUBLICATION,
                key=key,
                labels=["TK"],
                props=props,
            )

            pending_docs.append(node.to_document())
            publications.append(node)

        # Batch-upsert all publication nodes.
        for batch_start in range(0, len(pending_docs), self._NODE_BATCH_SIZE):
            self.store.bulk_insert_or_update_nodes(
                COLLECTION_PUBLICATIONS,
                pending_docs[batch_start : batch_start + self._NODE_BATCH_SIZE],
            )

        logger.info(
            "Created %d TK publication nodes.",
            len(publications),
        )

        return publications

    @staticmethod
    def _first_non_empty(values: Iterable[Any]) -> str | None:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None
