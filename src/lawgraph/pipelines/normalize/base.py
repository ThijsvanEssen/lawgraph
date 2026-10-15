from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.core.time import iso_timestamp
from lawgraph.db import CountingStore, GraphStore, NodeWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.base import PipelineBase

logger = get_logger(__name__)


def _payload_size(record: dict[str, Any]) -> int:
    """The characters of a record's text payload: what most of the work on it grows with."""
    text = record.get("payload_text")
    return len(text) if isinstance(text, str) else 0


class RawRecords:
    """The raw records of some kinds, streamed from the database by every ``for`` loop.

    Nothing is kept: a second loop reads them again. For pipelines that walk a large kind
    more than once, where a list would hold every payload for the whole run.
    """

    def __init__(
        self,
        pipeline: NormalizePipelineBase[Any],
        *,
        source: str,
        kinds: list[str],
        since: dt.datetime | None,
        batch_size: int,
    ) -> None:
        self._pipeline = pipeline
        self._options: dict[str, Any] = {
            "source": source,
            "kinds": kinds,
            "since": since,
            "batch_size": batch_size,
        }

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._pipeline._iter_raw_sources(**self._options)


# The raw records most pipelines read: a stream of raw_sources rows.
Records = Iterable[dict[str, Any]]


class NormalizePipelineBase[Raw](PipelineBase, ABC):
    """Base class for pipelines that normalize raw_sources records.

    A run is two steps: ``fetch_raw`` says what to read (*Raw*: mostly a stream of
    records, read as it is walked), ``write`` writes what it holds. A pipeline with nodes
    and edges writes its nodes first and passes what its edges need on as a dataclass.

    ``self.store`` is a ``CountingStore``: every node and edge a subclass or its
    helpers upsert through it is counted, and ``run`` reports those counts as
    ``created``/``updated`` on the result. Subclasses only record what the store
    cannot see: a record left out or unreadable, through ``self.progress``.
    """

    store: CountingStore

    def __init__(self, store: GraphStore) -> None:
        super().__init__(CountingStore(store))

    @abstractmethod
    def fetch_raw(self, *, since: dt.datetime | None = None) -> Raw:
        """The raw_sources records relevant for this pipeline (of the window *since*)."""
        raise NotImplementedError

    @abstractmethod
    def write(self, raw: Raw, result: PipelineResult) -> None:
        """Write the nodes and edges of *raw*."""
        raise NotImplementedError

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Fetch and write, with the counts of what was written."""
        result = PipelineResult()
        self.store.reset_counts()

        try:
            self.write(self.fetch_raw(since=since), result)
        except Exception:
            # The error goes to ``run_command``; what was written before it is in the database.
            logger.warning(
                "Written before the failure: %s.", self.store.writes.describe()
            )
            raise
        return self._counted(result)

    def _counted(self, result: PipelineResult) -> PipelineResult:
        """*result* with what the store wrote since ``reset_counts`` and what every loop
        counted (``add_outcomes``)."""
        writes = self.store.writes
        result.created += writes.created
        result.updated += writes.updated
        result.unchanged += writes.unchanged
        self.add_outcomes(result)
        logger.debug("Wrote: %s.", writes.describe())  # nodes and edges apart
        return result

    def _iter_raw_sources(
        self,
        *,
        source: str,
        kinds: list[str],
        since: dt.datetime | None = None,
        batch_size: int = 20,
        chronological: bool = False,
        after: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream raw_sources rows in small batches, each with its text payload; a slice:
        past the record key *after*, *limit* of them."""
        since_iso = iso_timestamp(since)
        # The total of a full run comes from the index; with a date every record would
        # have to be read to count it, so an incremental run shows no total and no ETA.
        sliced = bool(after) or limit is not None
        total = None if since_iso or sliced else self._count_raw_sources(source, kinds)
        progress = self._loop(f"{'/'.join(kinds)} records", total=total)
        rows = raw_queries.iter_raw_records(
            self.store,
            source=source,
            kinds=kinds,
            since_iso=since_iso,
            batch_size=batch_size,
            chronological=chronological,
            after=after,
            limit=limit,
        )
        yield from progress.track(self.store.with_payloads(rows), _payload_size)

    def _count_raw_sources(self, source: str, kinds: list[str]) -> int | None:
        return raw_queries.count_raw_records(self.store, source, kinds)

    def _upsert_nodes(self, nodes: Iterable[Node], *, batch_size: int = 500) -> int:
        """Bulk-upsert *nodes* (see ``NodeWriter``); returns how many were written."""
        with NodeWriter(self.store, batch_size=batch_size) as writer:
            writer.add_all(nodes)
        return writer.written

    # Thin delegates kept for the many subclasses calling ``self._payload_text(...)``
    # etc.; the logic lives in ``lawgraph.core.raw_records``.
    _payload_json = staticmethod(payload_json)
    _payload_text = staticmethod(payload_text)
    _meta = staticmethod(meta)
