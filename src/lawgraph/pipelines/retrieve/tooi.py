"""Retrieve pipeline for TOOI: the value list of every ministry."""

from __future__ import annotations

import datetime as dt

from lawgraph.clients.tooi import TooiClient
from lawgraph.config.constants import RAW_KIND_TOOI_MINISTRIES, SOURCE_TOOI
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord


class TooiRetrievePipeline(RetrievePipelineBase):
    """Store the latest version of the ministries list, one record (external id
    ``rwc_ministeries_compleet``), with its URL and the day it was read."""

    def __init__(self, store: ArangoStore, client: TooiClient | None = None) -> None:
        super().__init__(store)
        self.client = client or TooiClient()

    def fetch(self, **kwargs: object) -> list[RetrieveRecord]:
        url, items = self.client.ministries()
        return [
            RetrieveRecord(
                source=SOURCE_TOOI,
                kind=RAW_KIND_TOOI_MINISTRIES,
                external_id="rwc_ministeries_compleet",
                payload_json={"items": items},
                meta={"url": url, "read_on": dt.date.today().isoformat()},
            )
        ]
