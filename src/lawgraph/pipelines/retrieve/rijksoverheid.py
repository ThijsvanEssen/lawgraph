"""Retrieve pipeline for Rijksoverheid: the page of every cabinet since 1945."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.rijksoverheid import RijksoverheidClient
from lawgraph.config.constants import (
    RAW_KIND_RIJKSOVERHEID_CABINET,
    SOURCE_RIJKSOVERHEID,
)
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord


class RijksoverheidRetrievePipeline(RetrievePipelineBase):
    """Store the page of every cabinet the index links, one record per page: the HTML,
    with the URL and the day it was read."""

    def __init__(
        self, store: ArangoStore, client: RijksoverheidClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or RijksoverheidClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        slugs = self.client.cabinet_slugs()
        self.progress.expect(len(slugs))
        for slug in slugs:
            yield RetrieveRecord(
                source=SOURCE_RIJKSOVERHEID,
                kind=RAW_KIND_RIJKSOVERHEID_CABINET,
                external_id=slug,
                payload_text=self.client.cabinet_page(slug),
                meta={
                    "url": self.client.url(slug),
                    "read_on": dt.date.today().isoformat(),
                },
            )
