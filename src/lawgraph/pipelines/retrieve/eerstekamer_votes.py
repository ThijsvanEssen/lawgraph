"""Retrieve pipeline for the votes of the Eerste Kamer on bills (eerstekamer.nl).

One record per day of the list of votes (``ek-votes-day-html``, external id the date): the
part of the list of that day, from one page or two (a day that runs over a page). The list is
newest first, so an incremental run stops at the first page that ends before ``since``. The
list of rejected bills is stored whole on every run (``ek-rejected-html``, two pages).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EK_REJECTED,
    RAW_KIND_EK_VOTES_DAY,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import eerstekamer_votes
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class EerstekamerVotesRetrievePipeline(RetrievePipelineBase):
    """Store the list of votes on bills per day, and the list of rejected bills."""

    def __init__(
        self, store: ArangoStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(  # type: ignore[override]
        self, *, since: dt.date | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        yield from self._days(since)
        yield self._rejected()

    def _days(self, since: dt.date | None) -> Iterator[RetrieveRecord]:
        first = since.isoformat() if since else ""
        date: str | None = None
        parts: list[str] = []
        url = ""
        for page_url, page in self.client.vote_pages():
            days = eerstekamer_votes.days(page)
            for day, continued, fragment in days:
                if continued and day == date:
                    parts.append(fragment)
                    continue
                if date and date >= first:
                    yield self._day(date, parts, url)
                date, parts, url = day, [fragment], page_url
            if not days or all((day or "") < first for day, _, _ in days):
                break
        if date and date >= first:
            yield self._day(date, parts, url)

    def _day(self, date: str, parts: list[str], url: str) -> RetrieveRecord:
        return RetrieveRecord(
            source=SOURCE_EERSTEKAMER,
            kind=RAW_KIND_EK_VOTES_DAY,
            external_id=date,
            payload_text="".join(parts),
            meta={"url": url, "read_on": dt.date.today().isoformat()},
        )

    def _rejected(self) -> RetrieveRecord:
        pages = self.client.rejected_pages()
        return RetrieveRecord(
            source=SOURCE_EERSTEKAMER,
            kind=RAW_KIND_EK_REJECTED,
            external_id=eerstekamer_votes.REJECTED_PATH.strip("/"),
            payload_text="".join(page for _, page in pages),
            meta={"url": pages[0][0], "read_on": dt.date.today().isoformat()},
        )
