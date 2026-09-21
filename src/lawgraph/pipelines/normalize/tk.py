"""Normalize TK Zaak records into cases.

Every Zaak the Tweede Kamer handles becomes a Case — no filtering by kind;
what a case is about is the ``kind`` the source gives it. The documents of a
case are written by ``tk_cases``, which also draws the PART_OF edges to the
cases and dossiers they name.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
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
    ) -> Iterator[dict[str, Any]]:
        """Stream the TK Zaak raw records to normalize."""
        return self._iter_raw_sources(
            source=SOURCE_TK, kinds=[RAW_KIND_TK_ZAAK], since=since, batch_size=1000
        )

    def normalize_nodes(
        self,
        raw: Iterable[dict[str, Any]],
        result: PipelineResult,
    ) -> int:
        """Write the case node of each raw record as it is read; none is kept."""
        return self._normalize_cases(raw)

    def build_edges(
        self,
        raw: Iterable[dict[str, Any]],
        normalized: int,
    ) -> None:
        """None: a case is linked to its dossiers once the dossiers exist."""

    def _normalize_cases(self, raw_records: Iterable[dict[str, Any]]) -> int:
        """Case nodes, keyed by the Zaak identifier documents refer to."""
        writer = NodeWriter(self.store)
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

            writer.add(
                Node(
                    collection=COLLECTION_CASES,
                    type=NodeType.CASE,
                    key=make_node_key(external_id),
                    labels=["TK"],
                    props=props,
                )
            )

        writer.flush()
        logger.info("Normalized %d TK cases.", writer.written)
        return writer.written
