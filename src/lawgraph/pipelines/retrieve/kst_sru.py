"""Retrieve pipeline for the Kamerstukken of the Tweede Kamer of 1994-1995 to 2007-2008 (KOOP SRU).

The Tweede Kamer's own API (``retrieve tk``) is nearly complete from 2008-2009 on and holds a
few hundred papers of the years before; the SRU of the official publications lists them all,
from December 1994 on (before that only the scans of Staten-Generaal Digitaal). Each session
year is a search of its own.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import RAW_KIND_KST_SRU, SOURCE_KST
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

# The first session year of the SRU with structured papers, and the last before the Tweede
# Kamer's own API holds its papers.
FIRST_YEAR = 1994
LAST_YEAR = 2007


def session_years(first: int = FIRST_YEAR, last: int = LAST_YEAR) -> list[str]:
    """``["1994-1995", …, "2007-2008"]``: the session years that begin in *first* to *last*."""
    return [f"{year}-{year + 1}" for year in range(first, last + 1)]


class KstSruRetrievePipeline(RetrievePipelineBase):
    """Store the SRU record of every Tweede Kamer Kamerstuk of the years the Tweede Kamer's
    API lacks as ``kst-sru-json``."""

    def __init__(
        self, store: GraphStore, client: KamerstukClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or KamerstukClient()

    def fetch(
        self,
        *,
        years: Sequence[str] = (),
        since: str | None = None,
        limit: int | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """The papers of *years* (default ``session_years()``), ``since`` on
        ``dt.modified``; at most *limit* in all."""
        left = limit
        for year in years or session_years():
            if left is not None and left <= 0:
                return
            count = 0
            for document in self.client.iter_tk_kamerstukken(
                year, since=since, limit=left
            ):
                count += 1
                yield RetrieveRecord(
                    source=SOURCE_KST,
                    kind=RAW_KIND_KST_SRU,
                    external_id=document["identifier"],
                    payload_json=document,
                    meta={
                        "session_year": document.get("session_year"),
                        "dossier_number": document.get("dossier_number"),
                        "modified": document.get("modified"),
                    },
                )
            logger.info("Kamerstukken of the Tweede Kamer %s: %d.", year, count)
            if left is not None:
                left -= count
