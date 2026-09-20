"""Retrieve pipeline for the judgments of the Rechtspraak (data.rechtspraak.nl)."""

from __future__ import annotations

import datetime as dt
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

from .base import RESUME_WITHIN_HOURS, RetrievePipelineBase, RetrieveRecord

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
            for entry in self.rs.iter_index(
                courts=resolve_courts(courts), date_from=date_from, date_to=date_to
            ):
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

        for ecli, updated in todo.items():
            try:
                xml = self.rs.fetch_ecli_content(ecli)
            except Exception as exc:
                logger.warning("Skipping ECLI %s: %s", ecli, exc)
                continue
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
