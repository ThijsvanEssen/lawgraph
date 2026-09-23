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
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    SOURCE_TK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class TKDossiersRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for all parliamentary dossier entity types."""

    def __init__(self, *, store: ArangoStore, client: TKClient | None = None) -> None:
        super().__init__(store)
        self.client = client or TKClient()

    def run(  # type: ignore[override]  # its own options; not the fetch template of the base
        self,
        *,
        since: dt.datetime | None = None,
        decisions_since: dt.datetime | None = None,
        documents_since: dt.datetime | None = None,
        skip_members: bool = False,
        skip_decisions: bool = False,
        skip_documents: bool = False,
        dossier_number: int | None = None,
    ) -> PipelineResult:
        """Fetch and store all parliamentary entity types.

        Each entity type is stored immediately after fetching, so a mid-run
        interruption preserves already-completed entity types.

        Args:
            since: Only fetch records modified since this datetime.
                   Pass None for a full refresh.
            decisions_since: Override ``since`` for Stemming only.
                   Use to limit the very large Stemming dataset to a window.
            documents_since: Override ``since`` for Document only.
                   Recommended: pass '730d' (2 years) as a starting window;
                   a full fetch is ~400K+ records.
            skip_members: Skip the Persoon and Fractie fetches (slow, only
                needed periodically).
            skip_decisions: Skip the Stemming fetch entirely.
            skip_documents: Skip the Document (Kamerstuk) fetch entirely.
            dossier_number: Targeted backfill — fetch only the Kamerstukdossier
                with this number and the Documents that link to it, ignoring
                date filters and skipping all other entity types. Used to fill
                gaps for dormant dossiers whose stukken predate the window:
                without the dossier its documents are part of nothing and no
                law is legislated in it.
        """
        result = PipelineResult()

        if dossier_number is not None:
            self._fetch_and_store(
                result,
                RAW_KIND_TK_DOSSIER,
                "Id",
                lambda: self.client.fetch_dossiers(since=None, number=dossier_number),
            )
            self._fetch_and_store(
                result,
                RAW_KIND_TK_DOCUMENT,
                "Id",
                lambda: self.client.fetch_documents(
                    since=None, dossier_number=dossier_number
                ),
            )
            logger.info(
                "TKDossiersRetrievePipeline (dossier=%d): stored %d raw records, %d errors.",
                dossier_number,
                result.created,
                len(result.errors),
            )
            return result

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
        if not skip_decisions:
            vote_since = decisions_since if decisions_since is not None else since
            self._fetch_and_store(
                result,
                RAW_KIND_TK_STEMMING,
                "Id",
                lambda: self.client.fetch_stemmingen(since=vote_since),
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
        if not skip_members:
            self._fetch_and_store(
                result,
                RAW_KIND_TK_PERSOON,
                "Id",
                lambda: self.client.fetch_personen(),
            )
            self._fetch_and_store(
                result,
                RAW_KIND_TK_FRACTIE,
                "Id",
                lambda: self.client.fetch_fracties(),
            )
            self._fetch_and_store(
                result,
                RAW_KIND_TK_FRACTIEZETELPERSOON,
                "Id",
                lambda: self.client.fetch_fractie_zetel_personen(),
            )
        if not skip_documents:
            doc_since = documents_since if documents_since is not None else since
            self._fetch_and_store(
                result,
                RAW_KIND_TK_DOCUMENT,
                "Id",
                lambda: self.client.fetch_documents(since=doc_since),
            )

        logger.info(
            "TKDossiersRetrievePipeline: stored %d raw records, %d errors.",
            result.created,
            len(result.errors),
        )
        return result

    def _fetch_and_store(
        self,
        result: PipelineResult,
        kind: str,
        id_field: str,
        fetch_fn: Callable[[], Iterable[dict[str, Any]]],
    ) -> None:
        """Store the records of *fetch_fn* as they arrive and add the outcome to *result*.

        A failure halfway keeps what was stored: the count is that of the run so far.
        """
        outcome = self._store_all(self._records(kind, id_field, fetch_fn), what=kind)
        result.created += outcome.created
        result.skipped += outcome.skipped
        result.errors.extend(f"{kind}: {error}" for error in outcome.errors)

    def _records(
        self,
        kind: str,
        id_field: str,
        fetch_fn: Callable[[], Iterable[dict[str, Any]]],
    ) -> Iterator[RetrieveRecord]:
        # The first page says how many records the query matches.
        self.client.on_total = self.progress.expect
        for record in fetch_fn():
            external_id = str(record.get(id_field) or "")
            if not external_id:
                self.progress.fail(f"record without {id_field}")
                continue
            yield RetrieveRecord(
                source=SOURCE_TK,
                kind=kind,
                external_id=external_id,
                payload_json=record,
            )
