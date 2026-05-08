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
        stemmingen_since: dt.datetime | None = None,
        skip_personen: bool = False,
        skip_stemmingen: bool = False,
    ) -> PipelineResult:
        """Fetch and store all parliamentary entity types.

        Each entity type is stored immediately after fetching, so a mid-run
        interruption preserves already-completed entity types.

        Args:
            since: Only fetch records modified since this datetime.
                   Pass None for a full refresh.
            stemmingen_since: Override ``since`` for Stemming only.
                   Use to limit the very large stemmingen dataset to a window.
            skip_personen: Skip the Persoon fetch (slow, only needed periodically).
            skip_stemmingen: Skip the Stemming fetch entirely.
        """
        result = PipelineResult()

        self._fetch_and_store(
            result,
            RAW_KIND_TK_DOSSIER,
            "Id",
            lambda: self.client.fetch_dossiers(since=since),
        )
        self._fetch_and_store(
            result,
            RAW_KIND_TK_ACTIVITEIT,
            "Id",
            lambda: self.client.fetch_activiteiten(since=since),
        )
        if not skip_stemmingen:
            stem_since = stemmingen_since if stemmingen_since is not None else since
            self._fetch_and_store(
                result,
                RAW_KIND_TK_STEMMING,
                "Id",
                lambda: self.client.fetch_stemmingen(since=stem_since),
            )
        self._fetch_and_store(
            result,
            RAW_KIND_TK_TOEZEGGING,
            "Id",
            lambda: self.client.fetch_toezeggingen(since=since),
        )
        self._fetch_and_store(
            result,
            RAW_KIND_TK_COMMISSIE,
            "Id",
            lambda: self.client.fetch_commissies(),
        )
        if not skip_personen:
            self._fetch_and_store(
                result,
                RAW_KIND_TK_PERSOON,
                "Id",
                lambda: self.client.fetch_personen(),
            )

        logger.info(
            "TkDossiersRetrievePipeline: stored %d raw records, %d errors.",
            result.created,
            len(result.errors),
        )
        return result

    def _fetch_and_store(
        self,
        result: Any,
        kind: str,
        id_field: str,
        fetch_fn: Any,
    ) -> None:
        """Fetch records with *fetch_fn*, store immediately, update *result*."""
        try:
            records = fetch_fn()
            logger.info("Retrieved %d %s records", len(records), kind)
        except Exception as exc:
            result.add_error(f"fetch {kind} failed: {exc}")
            logger.error("fetch %s failed: %s", kind, exc)
            return
        stored = self._store_records(kind, id_field, records)
        result.created += stored

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
