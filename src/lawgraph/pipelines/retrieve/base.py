from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_RAW_SOURCES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.core.time import iso_timestamp
from lawgraph.db import ArangoStore
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

MAX_FAILURES_IN_A_ROW = 25
RESUME_WITHIN_HOURS = 24


@dataclass(frozen=True)
class RetrieveRecord:
    source: str
    kind: str
    external_id: str | None
    payload_json: dict | list | None = None
    payload_text: str | None = None
    meta: dict | None = None
    # False for a by-product of another record: stored, but not a step of the progress.
    counts: bool = True


class SourceDown(RuntimeError):
    """A source failed too many requests in a row."""


class FailureStreak:
    """Tells one missing document from a source that is down.

    A loop that skips a document it cannot fetch reports every failure with ``failed``
    and every success with ``ok``; the ``MAX_FAILURES_IN_A_ROW``-th failure in a row raises,
    so a dead source fails the step instead of ending as "nothing to do".
    """

    def __init__(self, source: str, limit: int = MAX_FAILURES_IN_A_ROW) -> None:
        self.source = source
        self.limit = limit
        self.count = 0

    def ok(self) -> None:
        self.count = 0

    def failed(self, what: str, exc: Exception) -> None:
        self.count += 1
        if self.count >= self.limit:
            raise SourceDown(
                f"{self.source}: {self.limit} requests in a row failed (last: {what}: "
                f"{exc}); the source seems to be down."
            ) from exc


def failure_reason(exc: Exception) -> str:
    """The cause of a failed request without the record it was for: ``HTTP 503``, ``Timeout``."""
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None):
        return f"HTTP {response.status_code}"
    return type(exc).__name__


def add_outcome(result: PipelineResult, progress: Progress) -> None:
    """What *progress* counted next to the stored records: skips, and one error per cause."""
    result.skipped += progress.skipped + progress.failed
    result.errors.extend(progress.errors())


def is_not_found(exc: Exception) -> bool:
    """HTTP 404: the source does not have the document, which is not a failure."""
    response = getattr(exc, "response", None)
    return response is not None and getattr(response, "status_code", None) == 404


class RetrievePipelineBase(PipelineBase):
    """Stores what a source yields. Every retrieve pipeline runs through ``_store_all``.

    A pipeline yields ``RetrieveRecord``s from ``fetch`` (or from a generator of its own that
    it hands to ``_store_all``) and tells ``self.progress`` what it left out: ``expect`` the
    number of records once known, ``skip`` a record on purpose, ``fail`` one that went wrong.
    """

    progress: Progress

    def __init__(self, store: ArangoStore) -> None:
        super().__init__(store)
        self.progress = Progress()

    def run(self, **kwargs: Any) -> PipelineResult:
        def records() -> Iterator[RetrieveRecord]:
            # Inside the loop, so a ``fetch`` that raises before its first record is an
            # error of the result like any other failure of the source.
            yield from self.fetch(**kwargs)

        return self._store_all(records())

    def _store_all(
        self, records: Iterable[RetrieveRecord], *, what: str = "records"
    ) -> PipelineResult:
        """Store *records* one by one, as they arrive, and report the progress.

        Nothing is held back until the end: a crash, an interrupt or a failing source in
        the middle keeps every record stored so far, and re-running only repeats the rest
        (stores are upserts). A failure of the source itself is an error of the result, and
        so is every reason a record failed for (once, with its count).
        """
        result = PipelineResult()
        progress = self.progress = Progress(what)
        try:
            for record in records:
                result.created += self._store(record, progress)
        except Exception as exc:
            msg = f"fetch() failed after {result.created} records were stored: {exc}"
            logger.error(msg)
            result.add_error(msg)
        finally:
            progress.finish()
        add_outcome(result, progress)
        return result

    def _store(self, record: RetrieveRecord, progress: Progress) -> int:
        """Store one record; the number stored (a failing store is counted, not raised)."""
        try:
            self._insert(record)
        except Exception as exc:
            where = f"{record.source}/{record.kind}/{record.external_id}: {exc}"
            progress.fail(f"could not be stored ({failure_reason(exc)})", where)
            return 0
        if record.counts:
            progress.ok()
        return 1

    def fetch(self, **kwargs: Any) -> Iterable[RetrieveRecord]:
        """Return (or yield) the raw source records that should be stored.

        Yield them where fetching is slow, so each is stored as soon as it is there.
        """
        return []

    def _recently_stored(
        self, source: str, kind: str, hours: int = RESUME_WITHIN_HOURS
    ) -> set[str]:
        """External ids of *kind* stored in the last *hours*: what an interrupted run did.

        A run that downloads one document per record skips these, so a re-run after a crash
        (or an interrupt) only does the rest, while a refresh a day later fetches everything
        again.
        """
        cutoff = iso_timestamp(
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
        )
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.fetched_at >= @cutoff
            RETURN r.external_id
        """
        rows = self.store.query(aql, {"source": source, "kind": kind, "cutoff": cutoff})
        done = {str(external_id) for external_id in rows if external_id}
        if done:
            logger.info(
                "Resuming: %d %s/%s records were stored in the last %d hours; skipping.",
                len(done),
                source,
                kind,
                hours,
            )
        return done

    def _stored_at(self, source: str, kind: str) -> dict[str, dt.datetime]:
        """``{external_id: fetched_at}`` of every stored record of *kind*.

        For sources that say when a record last changed: what is stored and newer than that
        does not have to be fetched again.
        """
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind
            RETURN {{id: r.external_id, at: r.fetched_at}}
        """
        stored: dict[str, dt.datetime] = {}
        for row in self.store.query(aql, {"source": source, "kind": kind}):
            try:
                at = dt.datetime.fromisoformat(str(row["at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if row.get("id"):
                stored[str(row["id"])] = (
                    at if at.tzinfo else at.replace(tzinfo=dt.timezone.utc)
                )
        return stored

    def _insert(self, record: RetrieveRecord) -> None:
        self.store.insert_raw_source(
            source=record.source,
            kind=record.kind,
            external_id=record.external_id,
            payload_json=record.payload_json,
            payload_text=record.payload_text,
            meta=record.meta,
        )
