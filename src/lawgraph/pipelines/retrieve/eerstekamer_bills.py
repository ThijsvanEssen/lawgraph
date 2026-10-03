"""Retrieve pipeline for the pages of the bills of the Eerste Kamer (eerstekamer.nl).

One record per bill page (``ek-bill-html``, external id its path), with the heading of the
list it was found under (``meta.status``: ``In schriftelijke voorbereiding``, …). Which bills:
those on the list of every committee of the Eerste Kamer and those the list of votes named
(``normalize eerstekamer-votes``: ``bill_url``). A run over a window reads the bills its
committees still handle and those voted on since ``since``; a run without ``since`` every
bill of the lists, their older pages too. A bill page has no date it changed, so each of
those is read again.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import RAW_KIND_EK_BILL, SOURCE_EERSTEKAMER
from lawgraph.config.settings import EERSTEKAMER_SITE
from lawgraph.core import eerstekamer_bills
from lawgraph.db import GraphStore
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek

from .base import RetrievePipelineBase, RetrieveRecord


class EerstekamerBillsRetrievePipeline(RetrievePipelineBase):
    """Store the pages of the bills of the Eerste Kamer."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(  # type: ignore[override]
        self, *, since: dt.date | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        status: dict[str, str] = {}
        for listed in self.client.listed_bills(older=since is None):
            # a finished bill comes with the votes of the window, or on a run over all
            if since is None or listed.status != eerstekamer_bills.FINISHED:
                status.setdefault(listed.path, listed.status)
        site = EERSTEKAMER_SITE.rstrip("/")
        for url in normalize_ek.voted_bill_urls(
            self.store, since.isoformat() if since else None
        ):
            if url.startswith(site + "/wetsvoorstel/"):
                status.setdefault(url[len(site) :], "")
        for path in sorted(status):
            url, page = self.client.bill_page(path)
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_BILL,
                external_id=path,
                payload_text=page,
                meta={"url": url, "read_on": today, "status": status[path] or None},
            )
