"""Retrieve pipeline: fetch parliamentary dossier entities from TK OData API.

Fetches and stores raw records for:
  - Kamerstukdossier
  - Activiteit (debates/hearings)
  - Stemming (votes, one record per fractie per motion)
  - Besluit "Stemmen - ..." on a bill or a budget, also without a vote (a hamerstuk)
  - Toezegging (ministerial commitments)
  - Commissie (parliamentary committees)
  - Persoon (parliamentary members)

All records are stored idempotently in `raw_sources` keyed by
(source="tk", kind=RAW_KIND_TK_*, external_id=TK GUID).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_BESLUIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_FRACTIEZETELVACATURE,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    SOURCE_TK,
)
from lawgraph.core import tk_records
from lawgraph.core.dossier_stages import LEGISLATIVE_KINDS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve.base import (
    RetrievePipelineBase,
    RetrieveRecord,
    missing_record,
)

logger = get_logger(__name__)

# The cases of a paper whose Besluit can come without a Stemming (withdrawn, postponed, held,
# lapsed): fetched apart, those alone (``fetch_bill_decisions(without_votes=True)``).
PAPER_DECISION_KINDS = ("Amendement", "Motie")


class TKDossiersRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for all parliamentary dossier entity types."""

    def __init__(self, *, store: GraphStore, client: TKClient | None = None) -> None:
        super().__init__(store)
        self.client = client or TKClient()

    def run(  # type: ignore[override]  # its own options; not the fetch template of the base
        self,
        *,
        since: dt.datetime | None = None,
        decisions_since: dt.datetime | None = None,
        documents_since: dt.datetime | None = None,
        commitments_since: dt.datetime | None = None,
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
            decisions_since: Override ``since`` for Stemming and Besluit only.
                   Use to limit the very large Stemming dataset to a window.
            commitments_since: Override ``since`` for Toezegging only (all of them, with
                the letters that fulfil them, are a few hundred pages).
            documents_since: Override ``since`` for Document only.
                   Recommended: pass '730d' (2 years) as a starting window;
                   a full fetch is ~400K+ records.
            skip_members: Skip the Persoon and Fractie fetches (slow, only
                needed periodically).
            skip_decisions: Skip the Stemming fetch, and that of the Besluiten on bills,
                entirely.
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
                RAW_KIND_TK_BESLUIT,
                "Id",
                lambda: self.client.fetch_bill_decisions(
                    LEGISLATIVE_KINDS, since=vote_since
                ),
            )
            self._fetch_unvoted(result, vote_since)
        self._fetch_and_store(
            result,
            RAW_KIND_TK_TOEZEGGING,
            "Id",
            lambda: self.client.fetch_toezeggingen(
                since=commitments_since if commitments_since is not None else since
            ),
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
            self._fetch_and_store(
                result,
                RAW_KIND_TK_FRACTIEZETELVACATURE,
                "Id",
                lambda: self.client.fetch_fractie_zetel_vacatures(),
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

    def run_unvoted(self, since: dt.datetime | None = None) -> PipelineResult:
        """Fetch only the Besluiten without a vote on an amendment or a motion, since
        *since* or all (about 25,000): the backfill of ``--mode unvoted``."""
        result = PipelineResult()
        self._fetch_unvoted(result, since)
        return result

    def _fetch_unvoted(self, result: PipelineResult, since: dt.datetime | None) -> None:
        self._fetch_and_store(
            result,
            RAW_KIND_TK_BESLUIT,
            "Id",
            lambda: self.client.fetch_bill_decisions(
                PAPER_DECISION_KINDS, since=since, without_votes=True
            ),
        )

    def run_gaps(self, numbers: list[str]) -> PipelineResult:
        """Fetch the dossiers with these *numbers* (every suffix of each) and all their
        documents. A number the Tweede Kamer has no dossier of (``tk-dossier-missing``), or
        whose papers it has not all either (``tk-document-missing``: nr. 2 to 10 of a
        dossier of before its records begin), is remembered, so it is not asked for again
        for a while."""
        return self._store_all(self._gap_records(numbers), what="dossiers named")

    def _gap_records(self, numbers: list[str]) -> Iterator[RetrieveRecord]:
        for number in numbers:
            dossiers = list(
                self._records(
                    RAW_KIND_TK_DOSSIER,
                    "Id",
                    partial(self.client.fetch_dossiers, since=None, number=int(number)),
                )
            )
            if not dossiers:
                yield missing_record(SOURCE_TK, RAW_KIND_TK_DOSSIER, number, status=200)
                continue
            yield from dossiers
            numbered: dict[str, set[int]] = {}
            for record in self._records(
                RAW_KIND_TK_DOCUMENT,
                "Id",
                partial(
                    self.client.fetch_documents, since=None, dossier_number=int(number)
                ),
            ):
                _count_number(numbered, number, record.payload_json or {})
                yield record
            if any(len(held) < max(held) for held in numbered.values()):
                yield missing_record(
                    SOURCE_TK, RAW_KIND_TK_DOCUMENT, number, status=200
                )

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


def _count_number(numbered: dict[str, set[int]], number: str, payload: Any) -> None:
    """Add the number of the paper *payload* to *numbered* (per suffix) when it is a
    Kamerstuk of dossier *number*."""
    own = tk_records.own_dossier(payload)
    sequence = payload.get("Volgnummer")
    if own is None or own[0] != number or not isinstance(sequence, int) or sequence < 1:
        return
    numbered.setdefault(own[1] or "", set()).add(sequence)
