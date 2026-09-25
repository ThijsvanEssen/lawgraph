"""Retrieve pipeline for Wikidata: the Dutch cabinets."""

from __future__ import annotations

from lawgraph.clients.wikidata import WikidataClient
from lawgraph.config.constants import RAW_KIND_WIKIDATA_CABINET, SOURCE_WIKIDATA
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord


class WikidataRetrievePipeline(RetrievePipelineBase):
    """Store every Dutch cabinet Wikidata knows, one record per cabinet."""

    def __init__(
        self, store: ArangoStore, client: WikidataClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or WikidataClient()

    def fetch(self, **kwargs: object) -> list[RetrieveRecord]:
        return [
            RetrieveRecord(
                source=SOURCE_WIKIDATA,
                kind=RAW_KIND_WIKIDATA_CABINET,
                external_id=cabinet["id"],
                payload_json=cabinet,
                meta={"name": cabinet["name"]},
            )
            for cabinet in self.client.cabinets()
        ]
