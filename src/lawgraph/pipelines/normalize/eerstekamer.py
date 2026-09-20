"""Normalize pipeline for the Kamerstukken of the Eerste Kamer."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    MAX_TITLE_CHARS,
    RAW_KIND_EK_KAMERSTUK,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date
from lawgraph.db import NodeWriter
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

_DOSSIER_RE = re.compile(r"^\s*(?P<number>\d+)(?:[\s-]+(?P<suffix>\S.*?))?\s*$")


def split_dossier_number(value: str | None) -> tuple[str | None, str | None]:
    """``"35925 VII"`` -> ``("35925", "VII")``; ``"36867"`` -> ``("36867", None)``.

    The Tweede Kamer stores the two parts as ``number`` and ``suffix`` of the dossier.
    """
    match = _DOSSIER_RE.match(value or "")
    if not match:
        return None, None
    return match["number"], match["suffix"]


class EerstekamerNormalizePipeline(NormalizePipelineBase):
    """Normalize the SRU records of Eerste Kamer Kamerstukken into documents."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EK_KAMERSTUK],
            since=since,
        )
        logger.info("Loaded %d Eerste Kamer raw_sources.", len(rows))
        return rows

    def normalize_nodes(
        self, raw: list[dict[str, Any]], result: PipelineResult
    ) -> dict[str, Node]:
        nodes: dict[str, Node] = {}
        writer = NodeWriter(self.store)

        for record in raw:
            payload = self._payload_json(record)
            if not payload or not isinstance(payload, dict):
                result.skipped += 1
                continue
            identifier = payload.get("identifier") or record.get("external_id")
            if not identifier:
                result.skipped += 1
                continue
            node = self._paper(str(identifier), payload)
            writer.add(node)
            nodes[node.key] = node

        writer.flush()
        logger.info("Eerste Kamer normalize: %d Kamerstukken.", len(nodes))
        return nodes

    def _paper(self, identifier: str, payload: dict[str, Any]) -> Node:
        kind = payload.get("kind") or ""
        number = payload.get("number") or ""
        dossier_number, dossier_suffix = split_dossier_number(
            payload.get("dossier_number")
        )
        title = payload.get("document_title") or payload.get("title") or ""
        dossier = " ".join(part for part in (dossier_number, dossier_suffix) if part)
        display_name = f"EK {dossier}, nr. {number}: {title}" if dossier else title

        props: dict[str, Any] = {
            "source": SOURCE_EERSTEKAMER,
            "external_id": identifier,
            "kind": kind,
            "number": number,
            "title": title,
            "subject": payload.get("dossier_title") or "",
            "session_year": payload.get("session_year") or "",
            "display_name": (display_name or identifier)[:MAX_TITLE_CHARS],
        }
        for name, value in (
            ("date", iso_date(payload.get("date"))),
            ("dossier_number", dossier_number),
            ("dossier_suffix", dossier_suffix),
            ("url", payload.get("url")),
        ):
            if value:
                props[name] = value

        return Node(
            collection=COLLECTION_DOCUMENTS,
            type=NodeType.DOCUMENT,
            key=make_node_key("ek", identifier),
            labels=["EersteKamer", "EK"],
            props=props,
        )

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> None:
        """None. A paper reaches the graph through its Tweede Kamer dossier.

        ``EerstekamerDossierLinkSemanticPipeline`` matches the dossier number.
        """
