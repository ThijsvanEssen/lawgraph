"""Retrieve pipeline for TOOI: the value list of every ministry, and the thesauri of the BWB
(its legal areas and its government themes)."""

from __future__ import annotations

import datetime as dt

from lawgraph.clients.tooi import LEGAL_AREAS_LIST, THEMES_LIST, TooiClient
from lawgraph.config.constants import (
    RAW_KIND_TOOI_MINISTRIES,
    RAW_KIND_TOOI_THESAURUS,
    SOURCE_TOOI,
)
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class TooiRetrievePipeline(RetrievePipelineBase):
    """Store the latest version of the ministries list (external id
    ``rwc_ministeries_compleet``) and of each thesaurus of the BWB (external id the name of
    the list), one record each, with its URL and the day it was read."""

    def __init__(self, store: GraphStore, client: TooiClient | None = None) -> None:
        super().__init__(store)
        self.client = client or TooiClient()

    def fetch(self, **kwargs: object) -> list[RetrieveRecord]:
        read_on = dt.date.today().isoformat()
        url, items = self.client.ministries()
        records = [
            RetrieveRecord(
                source=SOURCE_TOOI,
                kind=RAW_KIND_TOOI_MINISTRIES,
                external_id="rwc_ministeries_compleet",
                payload_json={"items": items},
                meta={"url": url, "read_on": read_on},
            )
        ]
        for value_list in (LEGAL_AREAS_LIST, THEMES_LIST):
            url, items = self.client.thesaurus(value_list)
            records.append(
                RetrieveRecord(
                    source=SOURCE_TOOI,
                    kind=RAW_KIND_TOOI_THESAURUS,
                    external_id=value_list.rsplit("/", 1)[-1],
                    payload_json={"items": items},
                    meta={"url": url, "read_on": read_on},
                )
            )
        return records
