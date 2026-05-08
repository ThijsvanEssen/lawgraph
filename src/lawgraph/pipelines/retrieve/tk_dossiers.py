"""Retrieve pipeline: fetch parliamentary dossier entities from TK OData API.

Fetches and stores raw records for:
  - Kamerstukdossier
  - Activiteit (debates/hearings)
  - Stemming (votes, one record per fractie per motion)
  - Toezegging (ministerial commitments)
  - Commissie (parliamentary committees)
  - Persoon (parliamentary members)

All records are stored idempotently in `raw_sources` keyed by
(source="tk", kind=RAW_KIND_TK_*, external_id=TK GUID).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.config.settings import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import PipelineResult

logger = get_logger(__name__)


class TkDossiersRetrievePipeline:
    """Retrieve pipeline for all parliamentary dossier entity types."""

    def __init__(self, *, store: ArangoStore, client: TKClient | None = None) -> None:
        self.store = store
        self.client = client or TKClient()

    def run(
        self,
        *,
        since: dt.datetime | None = None,
        skip_personen: bool = False,
    ) -> PipelineResult:
        """Fetch and store all parliamentary entity types.

        Args:
            since: Only fetch records modified since this datetime.
                   Pass None for a full refresh.
            skip_personen: Skip the Persoon fetch (slow, only needed periodically).
        """
        result = PipelineResult()

        fetches: list[tuple[str, str, list[dict]]] = []

        try:
            dossiers = self.client.fetch_dossiers(since=since)
            fetches.append((RAW_KIND_TK_DOSSIER, "Id", dossiers))
            logger.info("Retrieved %d Kamerstukdossier records", len(dossiers))
        except Exception as exc:
            result.add_error(f"fetch_dossiers failed: {exc}")
            logger.error("fetch_dossiers failed: %s", exc)

        try:
            activiteiten = self.client.fetch_activiteiten(since=since)
            fetches.append((RAW_KIND_TK_ACTIVITEIT, "Id", activiteiten))
            logger.info("Retrieved %d Activiteit records", len(activiteiten))
        except Exception as exc:
            result.add_error(f"fetch_activiteiten failed: {exc}")
            logger.error("fetch_activiteiten failed: %s", exc)

        try:
            stemmingen = self.client.fetch_stemmingen(since=since)
            fetches.append((RAW_KIND_TK_STEMMING, "Id", stemmingen))
            logger.info("Retrieved %d Stemming records", len(stemmingen))
        except Exception as exc:
            result.add_error(f"fetch_stemmingen failed: {exc}")
            logger.error("fetch_stemmingen failed: %s", exc)

        try:
            toezeggingen = self.client.fetch_toezeggingen(since=since)
            fetches.append((RAW_KIND_TK_TOEZEGGING, "Id", toezeggingen))
            logger.info("Retrieved %d Toezegging records", len(toezeggingen))
        except Exception as exc:
            result.add_error(f"fetch_toezeggingen failed: {exc}")
            logger.error("fetch_toezeggingen failed: %s", exc)

        try:
            commissies = self.client.fetch_commissies()
            fetches.append((RAW_KIND_TK_COMMISSIE, "Id", commissies))
            logger.info("Retrieved %d Commissie records", len(commissies))
        except Exception as exc:
            result.add_error(f"fetch_commissies failed: {exc}")
            logger.error("fetch_commissies failed: %s", exc)

        if not skip_personen:
            try:
                personen = self.client.fetch_personen()
                fetches.append((RAW_KIND_TK_PERSOON, "Id", personen))
                logger.info("Retrieved %d Persoon records", len(personen))
            except Exception as exc:
                result.add_error(f"fetch_personen failed: {exc}")
                logger.error("fetch_personen failed: %s", exc)

        for kind, id_field, records in fetches:
            stored = self._store_records(kind, id_field, records)
            result.created += stored

        logger.info(
            "TkDossiersRetrievePipeline: stored %d raw records, %d errors.",
            result.created,
            len(result.errors),
        )
        return result

    def _store_records(
        self,
        kind: str,
        id_field: str,
        records: list[dict[str, Any]],
    ) -> int:
        count = 0
        for record in records:
            external_id = str(record.get(id_field) or "")
            if not external_id:
                logger.warning("Skipping %s record without %s", kind, id_field)
                continue
            try:
                self.store.insert_raw_source(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=external_id,
                    payload_json=record,
                )
                count += 1
            except Exception as exc:
                logger.error("Failed to store %s %s: %s", kind, external_id, exc)
        return count
