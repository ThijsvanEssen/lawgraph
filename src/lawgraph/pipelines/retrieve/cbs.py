"""Retrieve pipeline for the CBS: the yearly tables "Gebieden in Nederland".

One ``cbs-gebieden-json`` record per table (external id its identifier, ``86247NED``) of each
year of the present court map (``core.court_districts.FIRST_YEAR`` on), with its columns and
rows, its year and when the catalogue says it last changed. A table is fetched again only
when the catalogue says it changed after it was stored. ``normalize cbs`` reads them.
"""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.clients.cbs import CbsClient
from lawgraph.config.constants import RAW_KIND_CBS_REGIONS, SOURCE_CBS
from lawgraph.core.court_districts import FIRST_YEAR
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class CbsRetrievePipeline(RetrievePipelineBase):
    """Store each table of areas since ``FIRST_YEAR`` that is new or changed."""

    def __init__(self, store: GraphStore, client: CbsClient | None = None) -> None:
        super().__init__(store)
        self.client = client or CbsClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dutch_today().isoformat()
        tables = [t for t in self.client.region_tables() if t["year"] >= FIRST_YEAR]
        changed = set(self._changed(SOURCE_CBS, RAW_KIND_CBS_REGIONS, tables))
        for table in tables:
            if table["identifier"] not in changed:
                continue
            url, data = self.client.table(table["identifier"])
            yield RetrieveRecord(
                source=SOURCE_CBS,
                kind=RAW_KIND_CBS_REGIONS,
                external_id=table["identifier"],
                payload_json={"year": table["year"], **data},
                meta={"url": url, "read_on": today, "modified": table["modified"]},
            )
