"""Retrieve pipeline for the judgments of the Rechtspraak (data.rechtspraak.nl)."""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Iterator, Sequence

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.constants import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.core.case_numbers import Referral
from lawgraph.core.courts import owms_terms
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore

from .base import (
    FETCH_WORKERS,
    RESUME_WITHIN_HOURS,
    RetrievePipelineBase,
    RetrieveRecord,
    missing_record,
)

logger = get_logger(__name__)


class RechtspraakRetrievePipeline(RetrievePipelineBase):
    """Store the XML of judgments, one ``rs-content`` record per ECLI."""

    def __init__(
        self, store: GraphStore, rs_client: RechtspraakClient | None = None
    ) -> None:
        super().__init__(store)
        self.rs = rs_client or RechtspraakClient()

    def _referring_decisions(
        self, referrals: Sequence[Referral]
    ) -> dict[str, dt.datetime | None]:
        """The decisions *referrals* name, from the index of each referral date (every
        court: the text names the court in words), by case number; one request per date."""
        found: dict[str, dt.datetime | None] = {}
        for date in sorted({r.date for r in referrals if r.date}):
            day = dt.date.fromisoformat(date)
            entries = list(self.rs.iter_index(date_from=day, date_to=day))
            for referral in (r for r in referrals if r.date == date):
                found.update(
                    (entry.ecli, entry.updated)
                    for entry in entries
                    if referral.names(entry.case_numbers)
                )
        if referrals:
            logger.info(
                "Rechtspraak: %d referrals of preliminary rulings, %d decisions found in "
                "the index of their dates.",
                len(referrals),
                len(found),
            )
        return found

    def fetch(
        self,
        *,
        courts: Sequence[str] | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        modified_from: dt.datetime | None = None,
        eclis: Sequence[str] | None = None,
        referrals: Sequence[Referral] | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """Yield the content of each judgment as it is downloaded.

        *courts* (names as in ``core.courts.owms_terms``) selects judgments through the index, by
        decision date when *date_from* is given; a judgment already stored and not changed
        since is skipped. *eclis* are fetched as they are, unless stored in the last 24 hours.
        *referrals* (by case number and date) are looked up in the index of their date.
        """
        stored = self._stored_at(SOURCE_RECHTSPRAAK, RAW_KIND_RS_CONTENT)
        todo: dict[str, dt.datetime | None] = {}
        for ecli, updated in self._referring_decisions(referrals or []).items():
            have = stored.get(ecli)
            if not (have and updated and have >= updated):
                todo[ecli] = updated

        if courts:
            skipped = 0
            terms = owms_terms(courts)
            listings = [
                self.rs.iter_index(courts=terms, date_from=date_from, date_to=date_to)
            ]
            if modified_from is not None:
                # Also what was published or corrected since, whenever it was decided: a
                # judgment published months after its decision is in no decision window.
                listings.append(
                    self.rs.iter_index(courts=terms, modified_from=modified_from)
                )
            for entry in itertools.chain(*listings):
                have = stored.get(entry.ecli)
                if have and entry.updated and have >= entry.updated:
                    skipped += 1
                else:
                    todo[entry.ecli] = entry.updated
            logger.info(
                "Rechtspraak %s (%s to %s): %d judgments to download, %d already stored "
                "and unchanged.",
                ", ".join(courts),
                date_from or "the start",
                date_to or "today",
                len(todo),
                skipped,
            )

        recent = dt.datetime.now(dt.UTC) - dt.timedelta(hours=RESUME_WITHIN_HOURS)
        for ecli in eclis or []:
            if not (stored.get(ecli) and stored[ecli] >= recent):
                todo.setdefault(ecli, None)

        wanted = self._without_missing(SOURCE_RECHTSPRAAK, RAW_KIND_RS_CONTENT, todo)

        def records(ecli: str, xml: str) -> list[RetrieveRecord]:
            updated = todo[ecli]
            return [
                RetrieveRecord(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RS_CONTENT,
                    external_id=ecli,
                    payload_text=xml,
                    meta={
                        "ecli": ecli,
                        "updated": updated.isoformat() if updated else None,
                    },
                )
            ]

        # Side by side: a judgment takes longer to arrive than the host asks between two.
        yield from self._download_each(
            wanted,
            self.rs.fetch_ecli_content,
            records,
            source="Rechtspraak",
            missing=lambda ecli, status: missing_record(
                SOURCE_RECHTSPRAAK,
                RAW_KIND_RS_CONTENT,
                ecli,
                listed=todo[ecli] is not None,  # named by the index, not by a citation
                status=status,
            ),
            workers=FETCH_WORKERS,
        )
