"""Retrieve pipeline for the composition of the Eerste Kamer (eerstekamer.nl).

The pages: the lists of factions (``/fracties``) and committees (``/commissies``), the page of
each faction and committee they name, and the plan of the hall (``/wie_zit_waar``), about 40.
The site gives the composition of today only, so every run reads them all again. A page whose
content differs from its newest stored version is stored as a new version
(``ek-composition-html``, external id ``<path>@<day>``, ``ek_composition.version_id``;
``read_on`` that day); one that does not only gets ``last_read_on`` today on that version.
Raw so keeps every composition that was read, and when.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EERSTEKAMER_COMPOSITION,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_composition as ec
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class EerstekamerCompositionRetrievePipeline(RetrievePipelineBase):
    """Store the pages of the factions and committees of the Eerste Kamer that changed."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        return self.records(self.client.composition_pages(), dutch_today().isoformat())

    def records(
        self, pages: Iterable[tuple[str, str, str]], today: str
    ) -> Iterator[RetrieveRecord]:
        """The record of each of *pages* (path, url, html) read *today*: a new version when
        it differs from the newest stored one, else that version read again."""
        stored = ec.newest_versions(
            self._stored_records(SOURCE_EERSTEKAMER, RAW_KIND_EERSTEKAMER_COMPOSITION)
        )
        for path, url, page in pages:
            newest = stored.get(path)
            if newest is not None and payload_text(newest) == page:
                external_id = str(newest["external_id"])
                read = {**meta(newest), "url": url, "last_read_on": today}
            else:
                external_id = ec.version_id(path, today)
                read = {"url": url, "read_on": today, "last_read_on": today}
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EERSTEKAMER_COMPOSITION,
                external_id=external_id,
                payload_text=page,
                meta=read,
            )
