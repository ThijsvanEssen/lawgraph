from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import COLLECTION_RAW_SOURCES
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import ArangoStore
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)

PROGRESS_EVERY = 1000
RESUME_WITHIN_HOURS = 24


@dataclass(frozen=True)
class RetrieveRecord:
    source: str
    kind: str
    external_id: str | None
    payload_json: dict | list | None = None
    payload_text: str | None = None
    meta: dict | None = None


class RetrievePipelineBase(PipelineBase):
    def __init__(self, store: ArangoStore) -> None:
        super().__init__(store)

    def run(self, **kwargs: Any) -> PipelineResult:
        """Store the records of ``fetch`` one by one, as they arrive.

        Nothing is held back until the end: a crash, an interrupt or a failing source in
        the middle keeps every record stored so far, and re-running only repeats the rest
        (stores are upserts). A failure of ``fetch`` itself is an error of the result.
        """
        result = PipelineResult()
        name = self.__class__.__name__
        try:
            for record in self.fetch(**kwargs):
                self._store(record, result)
                stored = result.created + result.skipped
                if stored % PROGRESS_EVERY == 0:
                    logger.info("%s: %d records stored so far.", name, result.created)
        except Exception as exc:
            msg = f"fetch() failed after {result.created} records were stored: {exc}"
            logger.error(msg)
            result.add_error(msg)
        return result

    def _store(self, record: RetrieveRecord, result: PipelineResult) -> None:
        try:
            self._insert(record)
            result.created += 1
        except Exception as exc:
            msg = f"Failed to store {record.source}/{record.kind}/{record.external_id}: {exc}"
            logger.error(msg)
            result.add_error(msg)
            result.skipped += 1

    def fetch(self, **kwargs: Any) -> Iterable[RetrieveRecord]:
        """Return (or yield) the raw source records that should be stored.

        Yield them where fetching is slow, so each is stored as soon as it is there.
        Pipelines that implement complex multi-mode retrieval (BWB, Staatsblad)
        override run() directly instead of implementing fetch(), in which case
        fetch() is never called by the base and should not be overridden.
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
