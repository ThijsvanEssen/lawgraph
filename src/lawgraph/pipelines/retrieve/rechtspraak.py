"""Retrieve pipeline for the judgments of the Rechtspraak (data.rechtspraak.nl)."""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Iterator, Sequence

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.constants import RAW_KIND_RECHTSPRAAK_CONTENT, SOURCE_RECHTSPRAAK
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
    """Store the XML of judgments, one ``rs-content`` record per ECLI; of a judgment the
    Rechtspraak withdrew, a record without its XML that says so (``meta.withdrawn``)."""

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
            entries = list(self.rs.iter_index(from_date=day, to_date=day))
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

    def _withdrawals(
        self, since: dt.datetime, stored: dict[str, dt.datetime]
    ) -> Iterator[RetrieveRecord]:
        """A record of every ECLI the Rechtspraak withdrew since *since*, of every court,
        unless one stored after the withdrawal: its payload empty, so no word of the
        judgment is kept (the stored XML is overwritten), its ``meta.withdrawn`` how
        (``IndexEntry.withdrawn``). ``normalize rechtspraak`` makes a stub of it."""
        withdrawn = 0
        for entry in self.rs.iter_index(modified_from=since, documents=False):
            if not entry.withdrawn:
                continue  # published: the listings of the documents fetch it
            have = stored.get(entry.ecli)
            if have and entry.updated and have >= entry.updated:
                continue
            withdrawn += 1
            yield RetrieveRecord(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RECHTSPRAAK_CONTENT,
                external_id=entry.ecli,
                payload_text="",
                meta={
                    "ecli": entry.ecli,
                    "updated": entry.updated.isoformat() if entry.updated else None,
                    "withdrawn": entry.withdrawn,
                },
            )
        logger.info("Rechtspraak: %d judgments withdrawn since %s.", withdrawn, since)

    def fetch(
        self,
        *,
        courts: Sequence[str] | None = None,
        from_date: dt.date | None = None,
        to_date: dt.date | None = None,
        modified_from: dt.datetime | None = None,
        withdrawn_from: dt.datetime | None = None,
        eclis: Sequence[str] | None = None,
        referrals: Sequence[Referral] | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """Yield the content of each judgment as it is downloaded.

        *courts* (names as in ``core.courts.owms_terms``) selects judgments through the index, by
        decision date when *from_date* is given; a judgment already stored and not changed
        since is skipped. *withdrawn_from*: first what the Rechtspraak withdrew since then
        (``_withdrawals``). *eclis* are fetched as they are, unless stored in the last 24
        hours. *referrals* (by case number and date) are looked up in the index of their
        date.
        """
        stored = self._stored_at(SOURCE_RECHTSPRAAK, RAW_KIND_RECHTSPRAAK_CONTENT)
        if withdrawn_from is not None:
            yield from self._withdrawals(withdrawn_from, stored)
        todo: dict[str, dt.datetime | None] = {}
        for ecli, updated in self._referring_decisions(referrals or []).items():
            have = stored.get(ecli)
            if not (have and updated and have >= updated):
                todo[ecli] = updated

        if courts:
            skipped = 0
            terms = owms_terms(courts)
            listings = [
                self.rs.iter_index(courts=terms, from_date=from_date, to_date=to_date)
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
                from_date or "the start",
                to_date or "today",
                len(todo),
                skipped,
            )

        recent = dt.datetime.now(dt.UTC) - dt.timedelta(hours=RESUME_WITHIN_HOURS)
        for ecli in eclis or []:
            if not (stored.get(ecli) and stored[ecli] >= recent):
                todo.setdefault(ecli, None)

        wanted = self._without_missing(
            SOURCE_RECHTSPRAAK, RAW_KIND_RECHTSPRAAK_CONTENT, todo
        )

        def records(ecli: str, xml: str) -> list[RetrieveRecord]:
            updated = todo[ecli]
            return [
                RetrieveRecord(
                    source=SOURCE_RECHTSPRAAK,
                    kind=RAW_KIND_RECHTSPRAAK_CONTENT,
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
                RAW_KIND_RECHTSPRAAK_CONTENT,
                ecli,
                listed=todo[ecli] is not None,  # named by the index, not by a citation
                status=status,
            ),
            workers=FETCH_WORKERS,
        )
