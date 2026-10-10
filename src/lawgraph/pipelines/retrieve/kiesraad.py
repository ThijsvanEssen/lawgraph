"""Retrieve pipeline for the results of the elections of the Eerste Kamer (Kiesraad).

The page of each election in the Kiesraad's databank (``kiesraad-ek-result-html``, external id
its code: ``EK20230530``), once per election (``core.kiesraad.EK_ELECTIONS``): a result is
final. Each starts a term of the seats per day of the Eerste Kamer
(``normalize eerstekamer-seats``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.kiesraad import KiesraadClient
from lawgraph.config.constants import RAW_KIND_KIESRAAD_EK_RESULT, SOURCE_KIESRAAD
from lawgraph.core.kiesraad import EK_ELECTIONS
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord


class KiesraadRetrievePipeline(RetrievePipelineBase):
    """Store the page of each election of the Eerste Kamer not stored yet."""

    def __init__(self, store: GraphStore, client: KiesraadClient | None = None) -> None:
        super().__init__(store)
        self.client = client or KiesraadClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        stored = set(self._stored_at(SOURCE_KIESRAAD, RAW_KIND_KIESRAAD_EK_RESULT))
        for code in EK_ELECTIONS:
            if code in stored:
                continue
            url, page = self.client.election(code)
            yield RetrieveRecord(
                source=SOURCE_KIESRAAD,
                kind=RAW_KIND_KIESRAAD_EK_RESULT,
                external_id=code,
                payload_text=page,
                meta={"url": url, "read_on": today},
            )
