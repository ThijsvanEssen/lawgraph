"""Who issued each stored publication of the Staatsblad and the Staatscourant.

The XML of a publication does not name who issued it; the record of the SRU of the KOOP
repository does (``dcterms:creator``: ``Ministerie van Financiën``). For every stored record
of a publication whose meta does not hold that yet, the SRU is asked
(``KoopPublicationClient.creators_of``, fifty to a query) and its creators and day of
publication are written into the meta (``core.publication_creators``): the payload stays as
it is, only the meta and ``fetched_at`` change, so ``normalize`` reads the record again. A
publication the SRU holds no record of gets an empty list: asked, and it names none.

A record fetched again (a publication modified at the source) comes without them and is
asked again. ``--limit`` bounds a run: the daily run asks for the new ones, a backfill goes in
slices.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import batched
from typing import Any, ClassVar

from lawgraph.clients.koop_publications import (
    CREATORS_PER_QUERY,
    KoopPublicationClient,
    PublicationKind,
)
from lawgraph.core.publication_creators import META_CREATORS, META_PUBLISHED
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

from .base import RetrievePipelineBase, RetrieveRecord

# The publications a run asks for without ``--limit``: the new ones of a day, many times
# over (100 queries, a few minutes). A backfill passes its own.
PER_RUN = 5_000


def with_creators(
    record: dict[str, Any], found: dict[str, Any] | None
) -> RetrieveRecord:
    """The stored *record* again, with what the SRU said of it (*found*: ``{creators,
    published}``, ``None`` for no record) in its meta."""
    meta = {
        **(record.get("meta") or {}),
        META_CREATORS: (found or {}).get("creators") or [],
        META_PUBLISHED: (found or {}).get("published"),
    }
    return RetrieveRecord(
        source=record["source"],
        kind=record["kind"],
        external_id=record["external_id"],
        meta=meta,
        stored=record,
    )


class PublicationCreatorsRetrievePipeline(RetrievePipelineBase):
    """Write the creators of the stored records of ``source``/``kind`` into their meta."""

    source: ClassVar[str]
    kind: ClassVar[str]  # the raw kind of the publication's XML
    publication: ClassVar[PublicationKind]

    def __init__(
        self,
        store: GraphStore,
        client: KoopPublicationClient | None = None,
        limit: int | None = PER_RUN,
    ) -> None:
        super().__init__(store)
        self.client = client or KoopPublicationClient(self.publication)
        self.limit = limit

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        todo = list(
            raw_queries.without_creators(
                self.store, source=self.source, kind=self.kind, limit=self.limit
            )
        )
        self.progress.expect(len(todo))
        for chunk in batched(todo, CREATORS_PER_QUERY, strict=False):
            found = self.client.creators_of([r["external_id"] for r in chunk])
            for record in chunk:
                yield with_creators(record, found.get(record["external_id"]))
