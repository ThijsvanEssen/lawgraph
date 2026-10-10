"""Retrieve pipeline for the pages of the motions of the Eerste Kamer (eerstekamer.nl,
``/motiedossier/…``, ``ek-motion-html``, external id its path): what a motion asks, its key
data and who submitted and co-signed it (``core.ek_motions``).

The motions are those the list of votes named (``motion_url`` of the decisions on a motion,
``normalize eerstekamer-votes``); a page not stored is fetched, once: a motion's page does not
change after its vote. ``limit`` caps the pages of one run (the first run, some 700 pages at the
host's interval, goes in slices); the log says how many are left after it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import RAW_KIND_EK_MOTION, SOURCE_EERSTEKAMER
from lawgraph.config.settings import EERSTEKAMER_SITE
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.db.queries.normalize import eerstekamer as normalize_ek

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class EerstekamerMotionsRetrievePipeline(RetrievePipelineBase):
    """Store the page of every motion of the Eerste Kamer voted on and not stored yet."""

    def __init__(
        self,
        store: GraphStore,
        client: EerstekamerSiteClient | None = None,
        *,
        limit: int | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()
        self.limit = limit

    def wanted(self) -> list[str]:
        """The paths of the pages to fetch, in order."""
        stored = self._stored_at(SOURCE_EERSTEKAMER, RAW_KIND_EK_MOTION)
        site = EERSTEKAMER_SITE.rstrip("/")
        paths = (
            url.removeprefix(site) for url in normalize_ek.voted_motion_urls(self.store)
        )
        return [path for path in paths if path.startswith("/") and path not in stored]

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        wanted = self.wanted()
        now = wanted[: self.limit] if self.limit is not None else wanted
        logger.info(
            "Eerste Kamer motion pages: %d wanted, %d in this run, %d left after it",
            len(wanted),
            len(now),
            len(wanted) - len(now),
        )
        for path in now:
            url, page = self.client.bill_page(path)
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_MOTION,
                external_id=path,
                payload_text=page,
                meta={"url": url, "read_on": today},
            )
