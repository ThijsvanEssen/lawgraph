"""Retrieve pipeline for the names of the bills of the Eerste Kamer (eerstekamer.nl).

One record per bill (``ek-bill-name-json``, external id its path) with the number and the name
its list of every bill gives it. A run over a window reads the first pages, which hold the
highest numbers; a run without ``since`` the whole list.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EERSTEKAMER_BILL_NAME,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.official_urls import ek_url
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord, listed

# The pages of the list a window reads: 200 bills, the newest numbers and their budgets.
WINDOW_PAGES = 10


class EerstekamerBillNamesRetrievePipeline(RetrievePipelineBase):
    """Store the name of each bill on the Eerste Kamer's list of every bill."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(
        self, *, since: dt.date | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        today = dutch_today().isoformat()
        bills = listed(
            list(self.client.indexed_bills(pages=WINDOW_PAGES if since else None)),
            "the bills of the Eerste Kamer",
        )
        for bill in bills:
            if not bill.label or not bill.name:
                self.progress.skip("no dossier number or name", bill.path)
                continue
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EERSTEKAMER_BILL_NAME,
                external_id=bill.path,
                payload_json={"label": bill.label, "name": bill.name},
                meta={"url": ek_url(bill.path), "read_on": today},
            )
