"""Retrieve pipeline: the actors of every Tweede Kamer Zaak, and nothing else.

``retrieve tk`` and ``retrieve tk-dossiers`` fetch a Zaak without its actors; this fetches
only those (who submitted it, its lead committee), a few hundred bytes a case, so the actors
of all of them can be fetched cheaply. A change of an actor moves the ``ApiGewijzigdOp`` of
its Zaak. Stored idempotently in ``raw_sources`` as (source="tk", kind="tk-case-actors",
external_id=TK GUID).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.tk import TKClient
from lawgraph.config.constants import RAW_KIND_TK_CASE_ACTORS, SOURCE_TK
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class TKCaseActorsRetrievePipeline(RetrievePipelineBase):
    """Retrieve the actors of the TK Zaken modified since a moment (all: from the epoch)."""

    def __init__(self, store: GraphStore, tk_client: TKClient | None = None) -> None:
        super().__init__(store)
        self.tk = tk_client or TKClient()

    def fetch(  # type: ignore[override]
        self, *, since: dt.datetime | None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        # The first page says how many records the query matches.
        self.tk.on_total = self.progress.expect
        for record in self.tk.fetch_case_actors(since=since):
            external_id = str(record.get("Id") or "")
            if not external_id:
                self.progress.fail("record without Id")
                continue
            yield RetrieveRecord(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_CASE_ACTORS,
                external_id=external_id,
                payload_json=record,
            )
