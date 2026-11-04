"""Retrieve pipeline for the pages of the bills of the Eerste Kamer (eerstekamer.nl).

One record per bill page (``ek-bill-html``, external id its path), with the heading of the
list it was found under (``meta.status``: ``In schriftelijke voorbereiding``, …). Which bills:
those on the list of every committee of the Eerste Kamer and those the list of votes named
(``normalize eerstekamer-votes``: ``bill_url``). A run over a window reads the bills its
committees still handle and those voted on since ``since``; a run without ``since`` every
bill of the lists, their older pages too. A bill page has no date it changed, so each of
those is read again.

And one record per bill (``ek-bill-name-json``) with the number and the name the Kamer's list
of every bill gives it: of a run over a window the first pages of that list, which hold the
highest numbers, else the whole list (``names_only``: nothing else, for that list alone).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EERSTEKAMER_BILL,
    RAW_KIND_EERSTEKAMER_BILL_NAME,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_bills
from lawgraph.core.official_urls import ek_path, ek_url
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek

from .base import RetrievePipelineBase, RetrieveRecord, listed

# The pages of the list of every bill a window reads: 200 bills, the newest numbers.
WINDOW_PAGES = 10


class EerstekamerBillsRetrievePipeline(RetrievePipelineBase):
    """Store the pages of the bills of the Eerste Kamer."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def _names(self, since: dt.date | None, today: str) -> Iterator[RetrieveRecord]:
        bills = self.client.indexed_bills(pages=WINDOW_PAGES if since else None)
        for bill in listed(list(bills), "the bills of the Eerste Kamer"):
            # an old number (``9 (R1684)``) names no dossier
            if bill.label and bill.name:
                yield RetrieveRecord(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EERSTEKAMER_BILL_NAME,
                    external_id=bill.path,
                    payload_json={"label": bill.label, "name": bill.name},
                    meta={"url": ek_url(bill.path), "read_on": today},
                )

    def fetch(
        self,
        *,
        since: dt.date | None = None,
        names_only: bool = False,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        today = dutch_today().isoformat()
        yield from self._names(since, today)
        if names_only:
            return
        status: dict[str, str] = {}
        for bill in self.client.listed_bills(older=since is None):
            # a finished bill comes with the votes of the window, or on a run over all
            if since is None or bill.status != ek_bills.FINISHED:
                status.setdefault(bill.path, bill.status)
        for url in normalize_ek.voted_bill_urls(
            self.store, since.isoformat() if since else None
        ):
            path = ek_path(url)
            if path and path.startswith("/wetsvoorstel/"):
                status.setdefault(path, "")
        for path in sorted(status):
            url, page = self.client.page(path)
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EERSTEKAMER_BILL,
                external_id=path,
                payload_text=page,
                meta={"url": url, "read_on": today, "status": status[path] or None},
            )
