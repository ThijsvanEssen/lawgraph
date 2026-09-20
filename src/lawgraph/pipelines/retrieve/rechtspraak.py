from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from typing import Any

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.constants import (
    RAW_KIND_RS_CONTENT,
    RAW_KIND_RS_INDEX,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.judgments import count_index_entries
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class RechtspraakRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that handles Rechtspraak index snapshots and contents."""

    def __init__(
        self, store: ArangoStore, rs_client: RechtspraakClient | None = None
    ) -> None:
        super().__init__(store)
        self.rs = rs_client or RechtspraakClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        eclis: Sequence[str] | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """Yield the content of each ECLI as it is downloaded.

        An ECLI stored in the last 24 hours is skipped (an interrupted run did it). The index
        is a separate call: ``run_index``.
        """
        done = self._recently_stored(SOURCE_RECHTSPRAAK, RAW_KIND_RS_CONTENT)
        todo = [ecli for ecli in eclis or [] if ecli not in done]
        logger.info("Fetching Rechtspraak content of %d ECLIs.", len(todo))
        for ecli in todo:
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
                meta={"ecli": ecli},
            )

    def run_full(
        self,
        *,
        extra_params: dict[str, Any] | None = None,
        max_records: int = 5_000_000,
    ) -> PipelineResult:
        """Paginate the entire Rechtspraak index without a date filter."""
        return self.run_index(
            since=None, extra_params=extra_params, max_records=max_records
        )

    def run_index(
        self,
        *,
        since: dt.datetime | None,
        extra_params: dict[str, Any] | None = None,
        max_records: int = 5_000_000,
    ) -> PipelineResult:
        """Paginate the Rechtspraak index, only what was modified since *since* if given.

        Fetches index pages with ``max=1000`` and ``from=N`` until a page smaller than
        the page size is returned or ``max_records`` is reached. Each page is stored as
        soon as it is fetched, as a separate ``RAW_KIND_RS_INDEX`` raw record keyed by its
        window and offset, so a re-run is idempotent and an interrupted run keeps its pages.
        """
        result = PipelineResult()
        page_size = 1000
        start = 0
        window = since.date().isoformat() if since else "all"

        logger.info("Rechtspraak index (modified since: %s): starting.", window)

        while start < max_records:
            params: dict[str, Any] = dict(extra_params or {})
            params["max"] = str(page_size)
            params["from"] = str(start)

            try:
                xml_text = self.rs.fetch_ecli_index_xml(
                    modified_since=since, extra_params=params
                )
            except Exception as exc:
                msg = f"Rechtspraak index fetch failed (from={start}): {exc}"
                logger.error(msg)
                result.add_error(msg)
                break

            entry_count = count_index_entries(xml_text)
            record = RetrieveRecord(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_INDEX,
                external_id=f"index_{window}_{start}",
                payload_text=xml_text,
                meta={
                    "from": start,
                    "max": page_size,
                    "full_load": since is None,
                    "modified_since": since.isoformat() if since else None,
                },
            )
            self._store(record, result)
            logger.info(
                "Rechtspraak index (%s): stored page from=%d (%d entries).",
                window,
                start,
                entry_count,
            )

            if entry_count < page_size:
                break
            start += page_size

        logger.info(
            "Rechtspraak index (%s) completed: %d pages stored, %d errors.",
            window,
            result.created,
            len(result.errors),
        )
        return result
