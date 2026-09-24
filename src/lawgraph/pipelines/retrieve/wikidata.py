"""Retrieve pipeline for Wikidata: the posts people held in Dutch cabinets."""

from __future__ import annotations

from lawgraph.clients.wikidata import WikidataClient
from lawgraph.config.constants import RAW_KIND_WIKIDATA_CABINET_POSTS, SOURCE_WIKIDATA
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord


class WikidataRetrievePipeline(RetrievePipelineBase):
    """Store every person who held a post in a Dutch cabinet, one record per person."""

    def __init__(
        self, store: ArangoStore, client: WikidataClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or WikidataClient()

    def fetch(self, **kwargs: object) -> list[RetrieveRecord]:
        return [
            RetrieveRecord(
                source=SOURCE_WIKIDATA,
                kind=RAW_KIND_WIKIDATA_CABINET_POSTS,
                external_id=person["id"],
                payload_json=person,
                meta={"name": person["name"]},
            )
            for person in self.client.cabinet_posts()
        ]
