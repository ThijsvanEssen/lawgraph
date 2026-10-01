"""Retrieve pipeline for the Instanties value list of the Rechtspraak."""

from __future__ import annotations

import datetime as dt

from lawgraph.clients.rechtspraak import RechtspraakClient
from lawgraph.config.constants import RAW_KIND_RS_INSTANTIES, SOURCE_RECHTSPRAAK
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class RechtspraakInstantiesRetrievePipeline(RetrievePipelineBase):
    """Store the value list of every court an ECLI can name, one record (external id
    ``Instanties``), with its URL and the day it was read."""

    def __init__(
        self, store: GraphStore, client: RechtspraakClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or RechtspraakClient()

    def fetch(self, **kwargs: object) -> list[RetrieveRecord]:
        url, xml = self.client.instanties()
        return [
            RetrieveRecord(
                source=SOURCE_RECHTSPRAAK,
                kind=RAW_KIND_RS_INSTANTIES,
                external_id="Instanties",
                payload_text=xml,
                meta={"url": url, "read_on": dt.date.today().isoformat()},
            )
        ]
