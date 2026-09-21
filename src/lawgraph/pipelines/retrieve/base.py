from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_RAW_SOURCES, RAW_KIND_MISSING_SUFFIX
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.progress import Progress
from lawgraph.core.time import iso_timestamp
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.db.raw import Failure, StoreUnavailable
from lawgraph.pipelines.base import STOP, PipelineBase

logger = get_logger(__name__)

MAX_FAILURES_IN_A_ROW = 25
RESUME_WITHIN_HOURS = 24
# How long a document that answered HTTP 404 is left alone. A document the source itself
# listed is probably on its way (listed before its file is there, or the source is in
# maintenance); one whose id was read in a citation may never have existed.
MISSING_FOR_DAYS = 30
MISSING_LISTED_FOR_DAYS = 3


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


# 4xx answers that are about us and not about the document: not allowed (a ban answers 403
# to everything) or too many requests.
_SOURCE_REFUSES = (401, 403, 429)


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
        """Count a failure of the source; an answer about this one document is not one.

        HTTP 4xx (but 429) says something about the document that was asked for, and a
        source that answers is not down: a run of those must not end the step.
        """
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None and 400 <= status < 500 and status not in _SOURCE_REFUSES:
            self.count = 0
            return
        self.count += 1
        if self.count >= self.limit:
            raise SourceDown(
                f"{self.source}: {self.limit} requests in a row failed (last: {what}: "
                f"{exc}); the source seems to be down."
            ) from exc


def missing_record(
    source: str, kind: str, external_id: str, *, listed: bool = False
) -> RetrieveRecord:
    """The record that remembers that *source* has no *kind* document for *external_id*.

    *listed*: the source itself named the document (an index, an SRU listing), so it is asked
    for again after ``MISSING_LISTED_FOR_DAYS`` instead of ``MISSING_FOR_DAYS``.
    """
    days = MISSING_LISTED_FOR_DAYS if listed else MISSING_FOR_DAYS
    retry_after = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    return RetrieveRecord(
        source=source,
        kind=kind + RAW_KIND_MISSING_SUFFIX,
        external_id=external_id,
        meta={"kind": kind, "status": 404, "retry_after": iso_timestamp(retry_after)},
        counts=False,
    )


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
        """Store *records* as they arrive, a buffer at a time, and report the progress.

        Nothing is held back until the end. A failing source and an interrupt write the
        buffer before the run ends, so they keep every record fetched; a crash of the process
        loses at most the last buffer (``RawSourceWriter``: 500 records, 8 MB or 5 seconds),
        and re-running only repeats the rest (stores are upserts). A failure of the source
        itself is an error of the result, and so is every reason a record failed for (once,
        with its count).
        """
        result = PipelineResult()
        progress = self.progress = Progress(what)
        by_products: set[str] = set()

        def written(stored: list[dict[str, Any]], failures: list[Failure]) -> None:
            result.created += sum(
                1 for doc in stored if not doc["kind"].endswith(RAW_KIND_MISSING_SUFFIX)
            )
            progress.ok(sum(1 for doc in stored if doc["_key"] not in by_products))
            for doc, reason in failures:
                where = f"{doc['source']}/{doc['kind']}/{doc['external_id']}: {reason}"
                progress.fail("could not be stored", where)

        try:
            with RawSourceWriter(self.store, on_flush=written) as writer:
                for record in records:
                    if STOP.is_set():
                        raise KeyboardInterrupt  # leaves the writer, which stores its buffer
                    doc = raw_source_doc(
                        source=record.source,
                        kind=record.kind,
                        external_id=record.external_id,
                        payload_json=record.payload_json,
                        payload_text=record.payload_text,
                        meta=record.meta,
                    )
                    if not record.counts:
                        by_products.add(doc["_key"])
                    writer.add(doc)
        except StoreUnavailable:
            # Not this source but the database: a pipeline with more to fetch (the next
            # entity type of tk-dossiers) must not go on downloading what it cannot store.
            logger.error("Stopping after %d records were stored.", result.created)
            raise
        except Exception as exc:
            msg = f"fetch() failed after {result.created} records were stored: {exc}"
            logger.error(msg)
            result.add_error(msg)
        finally:
            progress.finish()
        add_outcome(result, progress)
        return result

    def fetch(self, **kwargs: Any) -> Iterable[RetrieveRecord]:
        """Return (or yield) the raw source records that should be stored.

        Yield them where fetching is slow, so each is stored as soon as it is there.
        """
        return []

    def _without_missing(self, source: str, kind: str, ids: Iterable[str]) -> list[str]:
        """*ids* without those the source answered HTTP 404 for not long ago.

        A pipeline yields ``missing_record`` for such a document. Without it every run, and
        every iteration of ``expand-graph``, asks for the same missing documents again; when
        its ``retry_after`` has passed a document is tried once more.
        """
        ids = list(ids)
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.meta.retry_after > @now
            RETURN r.external_id
        """
        bind = {
            "source": source,
            "kind": kind + RAW_KIND_MISSING_SUFFIX,
            "now": iso_timestamp(dt.datetime.now(dt.timezone.utc)),
        }
        missing = {str(external_id) for external_id in self.store.query(aql, bind)}
        todo = [external_id for external_id in ids if external_id not in missing]
        if len(todo) < len(ids):
            logger.info(
                "%d %s/%s documents answered HTTP 404 not long ago; not asking again yet.",
                len(ids) - len(todo),
                source,
                kind,
            )
        return todo

    def _changed(
        self, source: str, kind: str, listed: Iterable[dict[str, Any]]
    ) -> list[str]:
        """The identifiers of *listed* SRU records that are not stored or changed since.

        A record says when it was last ``modified`` (a date). One that was stored on a later
        day is left alone, so a run over a window of two years downloads what is new or
        changed and not every publication of the window again.
        """
        stored = self._stored_at(source, kind)
        changed: list[str] = []
        for record in listed:
            identifier = record.get("identifier")
            if not identifier:
                continue
            have, modified = stored.get(identifier), record.get("modified")
            if have and modified and have.date().isoformat() > str(modified)[:10]:
                continue
            changed.append(identifier)
        return changed

    def _recently_stored(
        self, source: str, kind: str, hours: int = RESUME_WITHIN_HOURS
    ) -> set[str]:
        """External ids of *kind* stored in the last *hours*: what an interrupted run did.

        A run that downloads one document per record skips these, so a re-run after a crash
        (or an interrupt) only does the rest, while a refresh a day later fetches everything
        again.
        """
        done = self._stored_since(source, kind, hours)
        if done:
            logger.info(
                "Resuming: %d %s/%s records were stored in the last %d hours; skipping.",
                len(done),
                source,
                kind,
                hours,
            )
        return done

    def _stored_since(self, source: str, kind: str, hours: int) -> set[str]:
        cutoff = iso_timestamp(
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
        )
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
            FILTER r.source == @source AND r.kind == @kind AND r.fetched_at >= @cutoff
            RETURN r.external_id
        """
        rows = self.store.query(aql, {"source": source, "kind": kind, "cutoff": cutoff})
        return {str(external_id) for external_id in rows if external_id}

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
