"""Retrieve pipeline for the judgments of the Rechtspraak (data.rechtspraak.nl)."""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Iterator, Sequence

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.constants import (
    RAW_KIND_RS_CONTENT,
    RECHTSPRAAK_COURT_GROUPS,
    RECHTSPRAAK_COURTS,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

from .base import (
    RESUME_WITHIN_HOURS,
    FailureStreak,
    RetrievePipelineBase,
    RetrieveRecord,
    failure_reason,
    fetched_side_by_side,
    is_not_found,
    missing_record,
)

logger = get_logger(__name__)


def resolve_courts(names: Sequence[str]) -> list[str]:
    """OWMS terms of court names or groups (``hr``, ``rvs``, ``hoven``); unknown names raise."""
    terms: list[str] = []
    for name in names:
        for key in RECHTSPRAAK_COURT_GROUPS.get(name, (name,)):
            if key not in RECHTSPRAAK_COURTS:
                known = sorted({*RECHTSPRAAK_COURTS, *RECHTSPRAAK_COURT_GROUPS})
                raise ValueError(f"unknown court {name!r}; known: {', '.join(known)}")
            if RECHTSPRAAK_COURTS[key] not in terms:
                terms.append(RECHTSPRAAK_COURTS[key])
    return terms


class RechtspraakRetrievePipeline(RetrievePipelineBase):
    """Store the XML of judgments, one ``rs-content`` record per ECLI."""

    def __init__(
        self, store: ArangoStore, rs_client: RechtspraakClient | None = None
    ) -> None:
        super().__init__(store)
        self.rs = rs_client or RechtspraakClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        courts: Sequence[str] | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        modified_from: dt.datetime | None = None,
        eclis: Sequence[str] | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """Yield the content of each judgment as it is downloaded.

        *courts* (names as in ``resolve_courts``) selects judgments through the index, by
        decision date when *date_from* is given; a judgment already stored and not changed
        since is skipped. *eclis* are fetched as they are, unless stored in the last 24 hours.
        """
        stored = self._stored_at(SOURCE_RECHTSPRAAK, RAW_KIND_RS_CONTENT)
        todo: dict[str, dt.datetime | None] = {}

        if courts:
            skipped = 0
            terms = resolve_courts(courts)
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

        recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
            hours=RESUME_WITHIN_HOURS
        )
        for ecli in eclis or []:
            if not (stored.get(ecli) and stored[ecli] >= recent):
                todo.setdefault(ecli, None)

        wanted = self._without_missing(SOURCE_RECHTSPRAAK, RAW_KIND_RS_CONTENT, todo)
        self.progress.expect(len(wanted))
        streak = FailureStreak("Rechtspraak")
        # Side by side: a judgment takes longer to arrive than the host asks between two.
        for ecli, xml in fetched_side_by_side(wanted, self.rs.fetch_ecli_content):
            updated = todo[ecli]
            if isinstance(xml, Exception):
                exc = xml
                if is_not_found(exc):
                    self.progress.skip("no content (HTTP 404)", ecli)
                    streak.ok()
                    yield missing_record(
                        SOURCE_RECHTSPRAAK,
                        RAW_KIND_RS_CONTENT,
                        ecli,
                        listed=updated
                        is not None,  # named by the index, not by a citation
                    )
                else:
                    # An error of the step (exit 1), not a skip: a source that refuses
                    # everything must not end as "N skipped".
                    self.progress.fail(f"download failed ({failure_reason(exc)})", ecli)
                    streak.failed(ecli, exc)
                continue
            streak.ok()
            yield RetrieveRecord(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_CONTENT,
                external_id=ecli,
                payload_text=xml,
                meta={
                    "ecli": ecli,
                    "updated": updated.isoformat() if updated else None,
                },
            )
