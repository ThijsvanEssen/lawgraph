"""Retrieve pipeline for the composition of the Eerste Kamer (eerstekamer.nl).

One record per page (``ek-composition-html``, external id its path): the lists of factions
(``/fracties``) and committees (``/commissies``), the page of each faction and committee
they name, and the plan of the hall (``/wie_zit_waar``), about 40 pages. The site gives
the composition of today only, so every run reads it all again: a snapshot, dated by
``read_on``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import RAW_KIND_EK_COMPOSITION, SOURCE_EERSTEKAMER
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class EerstekamerCompositionRetrievePipeline(RetrievePipelineBase):
    """Store the pages of the factions and committees of the Eerste Kamer, as they are
    today."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        for path, url, page in self.client.composition_pages():
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_COMPOSITION,
                external_id=path,
                payload_text=page,
                meta={"url": url, "read_on": today},
            )
