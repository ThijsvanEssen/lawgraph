from __future__ import annotations

import datetime as dt
import json
from typing import Any, Iterable

from lawgraph.config.settings import (
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
    RAW_KIND_TK_DOCUMENTVERSIE,
    RAW_KIND_TK_ZAAK,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF_PROCEDURE,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline
from lawgraph.utils.display import make_display_name

logger = get_logger(__name__)


class TkNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns TK raw dumps into domain nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store, domain_profile="strafrecht")

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
    ) -> dict[str, Any]:
        """Translate raw TK payloads into procedure and publication nodes."""
        raw_zaken = raw.get("zaken", [])
        raw_docs = raw.get("documentversies", [])

        (
            procedures_by_external_id,
            procedure_strafrecht_nodes,
        ) = self._normalize_procedures(raw_zaken)
        publications, publication_strafrecht_nodes = self._normalize_publications(
            raw_docs
        )

        strafrecht_nodes = procedure_strafrecht_nodes + publication_strafrecht_nodes

        return {
            "procedures_by_external_id": procedures_by_external_id,
            "publications": publications,
            "strafrecht_nodes": strafrecht_nodes,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """Create strict PART_OF_PROCEDURE edges and semantic topic connections."""
        procedures_by_external_id: dict[str, Node] = normalized[
            "procedures_by_external_id"
        ]
        publications: list[Node] = normalized["publications"]

        raw_docs = raw.get("documentversies", [])
        logger.debug(
            "Linking %d TK DocumentVersie records to procedures.",
            len(raw_docs),
        )

        strict_edge_count = 0
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

            try:
                self.store.create_edge(
                    from_id=publication.id,
                    to_id=procedure_node.id,
                    relation=RELATION_PART_OF_PROCEDURE,
                    strict=True,
                    meta={"source": "tk-documentversie"},
                )
                strict_edge_count += 1
            except Exception as exc:  # pragma: no cover - logging only
                logger.error(
                    "Failed to create edge TK publication %s → procedure %s: %s",
                    publication.id,
                    procedure_node.id,
                    exc,
                )

        semantic_edge_count = 0
        topic_node = self._get_domain_topic_node()
        if topic_node:
            for node in normalized.get("strafrecht_nodes", []):
                if not node.id:
                    continue
                if self._ensure_related_topic_edge(
                    node=node,
                    topic_node=topic_node,
                    source="tk-normalize",
                ):
                    semantic_edge_count += 1
        else:
            logger.debug("No strafrecht topic found; skipping TK related-topic edges.")

        logger.info(
            "TK normalization completed: "
            "%d procedures, %d publications, %d strict edges, %d semantic edges.",
            len(procedures_by_external_id),
            len(publications),
            strict_edge_count,
            semantic_edge_count,
        )

        return strict_edge_count + semantic_edge_count

    def _normalize_procedures(
        self,
        raw_zaken: list[dict[str, Any]],
    ) -> tuple[dict[str, Node], list[Node]]:
        procedures_by_external_id: dict[str, Node] = {}
        strafrecht_nodes: list[Node] = []

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

            props: dict[str, Any] = {
                "external_id": external_id,
                "raw": payload,
            }

            if title_value:
                props["title"] = title_value

            is_strafrecht = self._is_strafrecht_tk_payload(payload)
            labels = ["TK"]
            if is_strafrecht:
                labels.append("Strafrecht")
                props["strafrecht_profile"] = "tk"

            props["display_name"] = make_display_name(NodeType.PROCEDURE, props)
            key = make_node_key(external_id)

            node = Node(
                collection=COLLECTION_PROCEDURES,
                type=NodeType.PROCEDURE,
                key=key,
                labels=labels,
                props=props,
            )

            inserted_node = self.store.insert_or_update(node)
            procedures_by_external_id[external_id] = inserted_node
            if is_strafrecht:
                strafrecht_nodes.append(inserted_node)

        logger.info(
            "Normalized %d TK procedures into nodes.",
            len(procedures_by_external_id),
        )

        return procedures_by_external_id, strafrecht_nodes

    def _normalize_publications(
        self,
        raw_docs: list[dict[str, Any]],
    ) -> tuple[list[Node], list[Node]]:
        publications: list[Node] = []
        strafrecht_nodes: list[Node] = []

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

            procedure_external_id = self._first_non_empty(
                [
                    payload.get("ZaakId"),
                    payload.get("ZaakNummer"),
                ]
            )

            props: dict[str, Any] = {
                "external_id": external_id,
                "raw": payload,
            }
            if procedure_external_id:
                props["procedure_external_id"] = procedure_external_id

            title_value = payload.get("Titel") or payload.get("TitelMetBijlagen")
            if title_value:
                props["title"] = title_value

            is_strafrecht = self._is_strafrecht_tk_payload(payload)
            labels = ["TK"]
            if is_strafrecht:
                labels.append("Strafrecht")
                props["strafrecht_profile"] = "tk"

            props["display_name"] = make_display_name(NodeType.PUBLICATION, props)
            key = make_node_key(external_id)

            node = Node(
                collection=COLLECTION_PUBLICATIONS,
                type=NodeType.PUBLICATION,
                key=key,
                labels=labels,
                props=props,
            )

            published_node = self.store.insert_or_update(node)
            publications.append(published_node)
            if is_strafrecht:
                strafrecht_nodes.append(published_node)

        logger.info(
            "Created %d TK publication nodes.",
            len(publications),
        )

        return publications, strafrecht_nodes

    def _is_strafrecht_tk_payload(self, payload: dict[str, Any]) -> bool:
        filters = self._load_domain_config().get("filters", {}).get("tk", {})
        title_keywords = filters.get("title_contains", [])
        dossier_keywords = filters.get("dossier_keywords", [])

        title_candidates = [
            payload.get("Titel"),
            payload.get("ZaakTitel"),
            payload.get("Omschrijving"),
            payload.get("TitelMetBijlagen"),
        ]
        for candidate in title_candidates:
            text = str(candidate) if candidate is not None else None
            if self._text_contains_keywords(text, title_keywords):
                return True

        if dossier_keywords:
            raw_payload = json.dumps(payload, default=str)
            if self._text_contains_keywords(raw_payload, dossier_keywords):
                return True

        return False

    @staticmethod
    def _first_non_empty(values: Iterable[Any]) -> str | None:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None
