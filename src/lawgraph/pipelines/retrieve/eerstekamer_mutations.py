"""Retrieve pipeline for the changes in the composition of the Eerste Kamer (eerstekamer.nl).

The lists of ``/personele_mutaties``, one per term (``ek-mutations-html``, external id its
path): the current term's read again on every run (a new item stands first), that of a term
that ended once. The page of each item they list (``ek-mutation-html``, external id its
path), once: a published item does not change. What they say is read by
``core.ek_changes``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EK_MUTATION,
    RAW_KIND_EK_MUTATIONS,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import ek_changes
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class EerstekamerMutationsRetrievePipeline(RetrievePipelineBase):
    """Store the lists of changes of every term and the page of each change not stored."""

    def __init__(
        self, store: GraphStore, client: EerstekamerSiteClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        stored = set(self._stored_at(SOURCE_EERSTEKAMER, RAW_KIND_EK_MUTATION))
        terms = set(self._stored_at(SOURCE_EERSTEKAMER, RAW_KIND_EK_MUTATIONS))
        for path, url, page in self.client.mutation_terms(terms):
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_MUTATIONS,
                external_id=path,
                payload_text=page,
                meta={"url": url, "read_on": today},
            )
            for item in ek_changes.term_page(page).items:
                if item.path in stored:
                    continue
                stored.add(item.path)
                item_url, item_page = self.client.bill_page(item.path)
                yield RetrieveRecord(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EK_MUTATION,
                    external_id=item.path,
                    payload_text=item_page,
                    meta={
                        "url": item_url,
                        "date": item.date,
                        "headline": item.headline,
                        "term": path,
                        "read_on": today,
                    },
                )
