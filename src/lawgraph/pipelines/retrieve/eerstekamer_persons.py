"""Retrieve pipeline for the pages of the members of the Eerste Kamer (eerstekamer.nl,
``/persoon/<slug>``, ``ek-person-html``, external id its path): who they are and in which
faction they sat, from when to when (``core.ek_persons``).

The members are those the stored composition lists (the faction pages of
``retrieve eerstekamer-composition``) and every person a stored change links
(``retrieve eerstekamer-mutations``, every term since 2003). A page not stored is fetched; a
stored one again when a change that links the person was fetched after it (they left, or
changed faction), and with ``sitting`` every sitting member's (the weekly run).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.eerstekamer_site import EerstekamerSiteClient
from lawgraph.config.constants import (
    RAW_KIND_EK_COMPOSITION,
    RAW_KIND_EK_MUTATION,
    RAW_KIND_EK_PERSON,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core import eerstekamer_composition, ek_changes
from lawgraph.core.raw_records import payload_text
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

from .base import RetrievePipelineBase, RetrieveRecord

FACTION_PREFIX = "/fractie/"


class EerstekamerPersonsRetrievePipeline(RetrievePipelineBase):
    """Store the page of every member of the Eerste Kamer not stored, or changed since."""

    def __init__(
        self,
        store: GraphStore,
        client: EerstekamerSiteClient | None = None,
        *,
        sitting: bool = False,
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerSiteClient()
        self.sitting = sitting

    def _records(self, kind: str) -> Iterator[dict]:
        rows = raw_queries.iter_raw_records(
            self.store,
            source=SOURCE_EERSTEKAMER,
            kinds=[kind],
            since_iso=None,
            batch_size=50,
        )
        return self.store.with_payloads(rows)

    def wanted(self) -> list[str]:
        """The paths of the pages to fetch, in order."""
        stored = self._stored_at(SOURCE_EERSTEKAMER, RAW_KIND_EK_PERSON)
        changed = self._stored_at(SOURCE_EERSTEKAMER, RAW_KIND_EK_MUTATION)
        sitting = {
            person.path
            for record in self._records(RAW_KIND_EK_COMPOSITION)
            if str(record.get("external_id") or "").startswith(FACTION_PREFIX)
            for person in eerstekamer_composition.page(
                payload_text(record) or ""
            ).members
        }
        # each person a change links, with when the newest of those changes was fetched
        named: dict[str, dt.datetime] = {}
        for record in self._records(RAW_KIND_EK_MUTATION):
            at = changed.get(str(record.get("external_id") or ""))
            for path in ek_changes.article(payload_text(record) or "", "", "").persons:
                if at is not None and (path not in named or named[path] < at):
                    named[path] = at
                named.setdefault(path, at or dt.datetime.min.replace(tzinfo=dt.UTC))
        wanted = []
        for path in sorted(sitting | set(named)):
            before = stored.get(path)
            if (
                before is None
                or (self.sitting and path in sitting)
                or (path in named and named[path] > before)
            ):
                wanted.append(path)
        return wanted

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        today = dt.date.today().isoformat()
        for path in self.wanted():
            url, page = self.client.bill_page(path)
            yield RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_PERSON,
                external_id=path,
                payload_text=page,
                meta={"url": url, "read_on": today},
            )
