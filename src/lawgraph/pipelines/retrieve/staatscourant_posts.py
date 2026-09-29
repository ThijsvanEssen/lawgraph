"""Retrieve pipeline: which ministry issued the publications that name a cabinet post.

For every post on the stored Rijksoverheid cabinet pages whose function names no ministry
("Minister voor Ontwikkelingssamenwerking"), held from 1995 on
(``core.post_ministries.staatscourant_query``): how many publications in the Staatscourant
and the Staatsblad name the function while the post was held, per creator (``dcterms:creator``,
``Ministerie van Buitenlandse Zaken``). One record per query (external id
``<phrase>|<from>|<to>``); ``normalize rijksoverheid`` reads them. A query of a post that has
ended is asked once; one of a post still held on every run.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.clients.staatscourant import StaatscourantClient
from lawgraph.config.constants import (
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RAW_KIND_STCRT_POST_CREATORS,
    SOURCE_RIJKSOVERHEID,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.cabinet_sources import build_cabinets
from lawgraph.core.post_ministries import query_id, staatscourant_query
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.rijksoverheid import parse_page
from lawgraph.db import ArangoStore
from lawgraph.db.queries import raw as raw_queries

from .base import RetrievePipelineBase, RetrieveRecord


class StaatscourantPostsRetrievePipeline(RetrievePipelineBase):
    """Store per post without a named ministry the creators of the publications naming it."""

    def __init__(
        self, store: ArangoStore, client: StaatscourantClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or StaatscourantClient()

    def queries(self) -> list[dict[str, Any]]:
        """The queries of the stored cabinet pages, less those of ended posts already
        stored."""
        rows = raw_queries.iter_raw_records(
            self.store,
            source=SOURCE_RIJKSOVERHEID,
            kinds=[RAW_KIND_RIJKSOVERHEID_CABINET],
            since_iso=None,
            batch_size=50,
        )
        pages = [
            {
                "slug": r.get("external_id"),
                "url": meta(r).get("url"),
                "read_on": meta(r).get("read_on"),
                "page": parse_page(payload_text(r) or ""),
            }
            for r in self.store.with_payloads(rows)
        ]
        stored = {
            row["id"]
            for row in raw_queries.fetch_times(
                self.store,
                source=SOURCE_STAATSCOURANT,
                kind=RAW_KIND_STCRT_POST_CREATORS,
            )
        }
        wanted: dict[str, dict[str, Any]] = {}
        for cabinet in build_cabinets(pages, lambda text: None):
            for post in cabinet["posts"]:
                query = staatscourant_query(post)
                if query and (query["to"] is None or query_id(query) not in stored):
                    wanted[query_id(query)] = query
        return list(wanted.values())

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        queries = self.queries()
        self.progress.expect(len(queries))
        today = dt.date.today().isoformat()
        for query in queries:
            creators = self.client.creators(
                query["phrase"], query["from"], query["to"] or today
            )
            yield RetrieveRecord(
                source=SOURCE_STAATSCOURANT,
                kind=RAW_KIND_STCRT_POST_CREATORS,
                external_id=query_id(query),
                payload_json={**query, "creators": dict(creators)},
                meta={"read_on": today},
            )
